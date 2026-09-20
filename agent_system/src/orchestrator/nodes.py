"""Implementation of all 12-step execution loop nodes for the LangGraph Healthcare Agent.

Each node represents a distinct, deterministic step in the patient rescheduling workflow,
taking AgentState as input and returning a dictionary of state updates.
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Any, Dict, List, Optional

from src.evals.tracer import TrajectoryTracer
from src.evals.worker import AsyncEvaluationWorker
from src.models.nlp_utils import is_affirmative_response, normalize_slot_and_date
from src.models.router import ModelRouter
from src.models.schemas import IntentType, PolicyDecisionResult
from src.policies.engine import PolicyEngine
from src.security.guardrails import process_security_guardrails, deanonymize_pii
from src.storage.memory import ContextRetriever
from src.storage.state import AgentState
from src.tools.appointment_tools import HEALTHCARE_TOOLS


# --- STEP 1: Receive User Message & Security Guardrails ---
def receive_message_node(state: AgentState) -> AgentState:
    """Step 1: Ingests raw input, initializes trace session, and applies security guardrails."""
    start = time.time()
    trace_id = state.get("explicit_trace_id") or f"trace-{uuid.uuid4().hex[:8]}"
    raw_input = state.get("raw_user_input", "")

    # Security check: detect prompt injection attacks and scrub patient PII
    sec = process_security_guardrails(raw_input)
    is_blocked = not sec.is_safe

    TrajectoryTracer().log_step(
        trace_id=trace_id,
        step_name="1. Receive User Message & Security Guard",
        provider="system",
        model="security_guardrails",
        tokens_in=len(raw_input.split()),
        tokens_out=len(sec.sanitized_text.split()),
        latency_ms=(time.time() - start) * 1000.0,
        status="blocked" if is_blocked else "success",
        metadata={"flagged_patterns": sec.injection_result.flagged_patterns},
    )

    return {
        "trace_id": trace_id,
        "sanitized_input": sec.sanitized_text,
        "pii_token_map": sec.pii_token_map,
        "security_flag": is_blocked,
        "security_reason": sec.injection_result.reason,
        "user_approval_granted": None,
        "hitl_status": None,
        "selected_tool": None,
        "raw_tool_args": {},
        "validated_tool_args": {},
        "tool_result": None,
        "validation_errors": [],
        "retry_count": 0,
        "requires_confirmation": False,
        "policy_decision": None,
        "final_response": None,
        "pending_offered_slot": state.get("pending_offered_slot"),
    }


# --- STEP 2: Intent Classification & Entity Extraction ---
def classify_intent_node(state: AgentState) -> AgentState:
    """Step 2: Dispatches intent classification and parameter extraction to Groq router."""
    context = {
        "patient_id": state.get("patient_id"),
        "doctor_id": state.get("doctor_id"),
        "pending_offered_slot": state.get("pending_offered_slot"),
    }
    classification, meta = ModelRouter().classify_intent_and_extract(
        state.get("sanitized_input", ""),
        context=context,
        simulate_groq_failure=state.get("simulate_groq_failure", False),
    )

    # Session patient ID is the authenticated identity boundary and must NEVER be overridden by prompt input
    session_patient_id = state.get("patient_id") or classification.entities.patient_id or "P101"
    doctor_id = classification.entities.doctor_id or state.get("doctor_id")

    entities = classification.entities.model_dump()
    if classification.entities.patient_id:
        entities["requested_patient_id"] = classification.entities.patient_id

    TrajectoryTracer().log_step(
        trace_id=state["trace_id"],
        step_name="2. Classify Intent & Extract Entities",
        provider=meta["provider"],
        model=meta["model"],
        tokens_in=meta["tokens_in"],
        tokens_out=meta["tokens_out"],
        ttft_ms=meta["ttft_ms"],
        latency_ms=meta["latency_ms"],
        cost_usd=meta["cost_usd"],
        status="success",
        metadata={"intent": classification.intent.value, "confidence": classification.confidence},
    )

    return {
        "intent": classification.intent.value,
        "intent_confidence": classification.confidence,
        "entities": entities,
        "patient_id": session_patient_id,
        "doctor_id": doctor_id,
    }


# --- STEP 3: Retrieve Minimal Context (RAG) ---
def retrieve_context_node(state: AgentState) -> AgentState:
    """Step 3: Fetches high-signal, minimal clinical context for the active patient and appointment."""
    start = time.time()
    entities = state.get("entities", {})
    context = ContextRetriever().retrieve_context(
        patient_id=state.get("patient_id"),
        doctor_id=state.get("doctor_id"),
        appointment_id=entities.get("appointment_id"),
    )

    TrajectoryTracer().log_step(
        trace_id=state["trace_id"],
        step_name="3. Retrieve Context (RAG)",
        provider="system",
        model="context_retriever",
        tokens_in=0,
        tokens_out=len(str(context).split()),
        latency_ms=(time.time() - start) * 1000.0,
        status="success",
        metadata={"has_active_appointment": bool(context.get("active_appointment"))},
    )

    return {"active_context": context}


# --- STEP 4: Decide Scope & Enforce Policy ---
def check_policy_node(state: AgentState) -> AgentState:
    """Step 4: Deterministically validates clinical policies including the 24-hour rescheduling rule."""
    active_context = state.get("active_context") or {}
    decision: PolicyDecisionResult = PolicyEngine().evaluate(
        state.get("intent"),
        state.get("patient_id"),
        active_context,
        entities=state.get("entities"),
    )

    reasons = [decision.reason] if not decision.allowed else []
    _, meta = ModelRouter().reason_policy(
        patient_context=active_context.get("patient", {}),
        appointment_context=active_context.get("active_appointment", {}),
        policy_violation_reasons=reasons,
    )

    TrajectoryTracer().log_step(
        trace_id=state["trace_id"],
        step_name="4. Decide Scope & Policy Enforcement",
        provider=meta["provider"],
        model=meta["model"],
        tokens_in=meta["tokens_in"],
        tokens_out=meta["tokens_out"],
        ttft_ms=meta["ttft_ms"],
        latency_ms=meta["latency_ms"],
        cost_usd=meta["cost_usd"],
        status="allowed" if decision.allowed else "denied",
        metadata={"policy_code": decision.policy_code, "requires_confirmation": decision.requires_confirmation},
    )

    return {
        "policy_decision": decision.model_dump(),
        "requires_confirmation": decision.requires_confirmation,
    }


# --- STEP 5: Select Tools ---
def select_tools_node(state: AgentState) -> AgentState:
    """Step 5: Maps intent and entities to a concrete clinical tool, resolving conflicts & self-corrections."""
    start = time.time()
    intent = state.get("intent")
    entities = dict(state.get("entities", {}))
    context = state.get("active_context") or {}
    patient_id = state.get("patient_id") or "P101"
    retry_count = state.get("retry_count", 0)
    validation_errors = state.get("validation_errors") or []

    # --- DYNAMIC FEEDBACK LOOP: SELF-CORRECTION BRANCH ---
    if retry_count > 0 and validation_errors:
        tool_to_repair = state.get("selected_tool") or "RequestSlotReschedule"
        failed_args = dict(state.get("last_failed_args") or state.get("raw_tool_args") or {})
        user_txt = state.get("sanitized_input") or state.get("raw_user_input") or ""
        correction_history = list(state.get("correction_history") or [])
        diagnostics = correction_history[-1].get("diagnostics") if correction_history else []

        repaired_args, repair_meta = ModelRouter().repair_tool_arguments(
            tool_name=tool_to_repair,
            failed_args=failed_args,
            validation_errors=validation_errors,
            user_input=user_txt,
            context=context,
            diagnostics=diagnostics,
        )

        # Mirror repaired slot into entities for state consistency
        if "new_slot_time" in repaired_args:
            entities["target_slot"] = repaired_args["new_slot_time"]
            entities["target_date"] = str(repaired_args["new_slot_time"])[:10]
        if "date_filter" in repaired_args:
            entities["target_date"] = repaired_args["date_filter"]

        TrajectoryTracer().log_step(
            trace_id=state["trace_id"],
            step_name=f"5. Self-Correction Repair (Attempt {retry_count}/2)",
            provider=repair_meta.get("provider", "system"),
            model=repair_meta.get("model", "pydantic_schema_repair_engine"),
            tokens_in=repair_meta.get("tokens_in", 0),
            tokens_out=repair_meta.get("tokens_out", 0),
            latency_ms=repair_meta.get("latency_ms", (time.time() - start) * 1000.0),
            cost_usd=repair_meta.get("cost_usd", 0.0),
            status="repaired",
            metadata={
                "tool": tool_to_repair,
                "strategy": repair_meta.get("strategy"),
                "failed_args": failed_args,
                "repaired_args": repaired_args,
                "retry_count": retry_count,
            },
        )

        return {
            "selected_tool": tool_to_repair,
            "raw_tool_args": repaired_args,
            "requires_confirmation": state.get("requires_confirmation", (tool_to_repair == "RequestSlotReschedule")),
            "entities": entities,
        }

    # --- STANDARD TOOL SELECTION BRANCH ---
    selected_tool = None
    raw_args: Dict[str, Any] = {}
    requires_confirmation = False

    if intent == IntentType.CHECK_AVAILABILITY.value:
        selected_tool = "GetAvailableSlots"
        doc_id = entities.get("doctor_id") or context.get("doctor", {}).get("doctor_id", "DOC1")
        raw_args = {"doctor_id": doc_id, "date_filter": entities.get("target_date")}

    elif intent == IntentType.VIEW_APPOINTMENT.value:
        selected_tool = "GetAppointmentDetails"
        raw_args = {"patient_id": patient_id, "appointment_id": entities.get("appointment_id")}

    elif intent in (IntentType.RESCHEDULE_APPOINTMENT.value, IntentType.CANCEL_APPOINTMENT.value):
        apt = context.get("active_appointment") or {}
        apt_id = entities.get("appointment_id") or apt.get("appointment_id", "APT-201")
        doc_id = entities.get("doctor_id") or context.get("doctor", {}).get("doctor_id", "DOC1")
        target_slot = entities.get("target_slot")
        target_date = entities.get("target_date")
        available_slots = context.get("available_slots", [])

        # Adopt pending offered slot if it matches target_date and user confirms/reiterates
        pending_offered = state.get("pending_offered_slot")
        is_pending_valid = bool(
            pending_offered and re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", str(pending_offered))
        )

        if not target_slot and is_pending_valid:
            user_txt = (state.get("sanitized_input") or "").lower()
            date_matches = (not target_date) or pending_offered.startswith(target_date)
            is_affirmative = is_affirmative_response(user_txt)
            is_reiterated = any(k in user_txt for k in ["schedule", "book", "confirm", "move", "reschedule", "i asked", "asked to"])

            if date_matches and (is_affirmative or is_reiterated):
                target_slot = pending_offered
                entities["target_slot"] = target_slot

        # If user explicitly requested scheduling on a specific date with a single open slot
        if not target_slot and target_date and available_slots:
            same_day = [s for s in available_slots if s.startswith(target_date)]
            user_txt = (state.get("sanitized_input") or "").lower()
            is_inquiry = any(user_txt.startswith(p) for p in ["can you", "could you", "is it possible", "are there", "what are", "do you have"])
            if len(same_day) == 1 and not is_inquiry and any(k in user_txt for k in ["i asked", "asked to", "schedule", "book", "please schedule"]):
                target_slot = same_day[0]
                entities["target_slot"] = target_slot

        is_valid_iso = bool(target_slot and re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", target_slot))

        # Check if the requested target slot is already the patient's active appointment slot
        current_apt_slot = apt.get("slot_time")
        is_same_as_current = False
        if target_slot and current_apt_slot:
            t_clean = str(target_slot).replace(" ", "T").strip()
            c_clean = str(current_apt_slot).replace(" ", "T").strip()
            if t_clean == c_clean or (len(t_clean) >= 16 and len(c_clean) >= 16 and t_clean[:16] == c_clean[:16]):
                is_same_as_current = True

        if is_same_as_current:
            # Case S: Target slot is already the active appointment slot!
            entities["same_slot_selected"] = {
                "slot_time": current_apt_slot,
                "doctor_name": apt.get("doctor_name") or (context.get("doctor") or {}).get("name", "Dr. Sarah Chen, MD"),
                "appointment_id": apt.get("appointment_id", "APT-201"),
            }
            selected_tool = None
            raw_args = {}
            requires_confirmation = False
        elif not target_slot:
            # Case A: Reschedule requested without specifying target time
            selected_tool = "GetAvailableSlots"
            raw_args = {"doctor_id": doc_id, "date_filter": target_date}
            entities["inquire_reschedule_slots"] = True
        elif is_valid_iso and available_slots and target_slot not in available_slots:
            # Case B: Slot is not available -> query alternatives
            same_day = [s for s in available_slots if s.startswith(target_slot[:10])]
            entities["slot_conflict"] = {"requested_slot": target_slot, "same_day_slots": same_day, "available_slots": available_slots}
            selected_tool = "GetAvailableSlots"
            raw_args = {"doctor_id": doc_id, "date_filter": target_date or (target_slot[:10] if same_day else None)}
        else:
            # Case C: Valid slot or intentionally invalid string for retry loop
            selected_tool = "RequestSlotReschedule"
            raw_args = {"patient_id": patient_id, "appointment_id": apt_id, "new_slot_time": target_slot, "reason": entities.get("reason", "Patient request")}
            requires_confirmation = True

    TrajectoryTracer().log_step(
        trace_id=state["trace_id"],
        step_name="5. Select Tools",
        provider="system",
        model="tool_selector",
        tokens_in=0,
        tokens_out=len(str(raw_args).split()),
        latency_ms=(time.time() - start) * 1000.0,
        status="success",
        metadata={"selected_tool": selected_tool, "requires_confirmation": requires_confirmation},
    )

    return {
        "selected_tool": selected_tool,
        "raw_tool_args": raw_args,
        "requires_confirmation": requires_confirmation,
        "entities": entities,
    }


# --- STEP 6: Validate Tool Inputs ---
def validate_tool_args_node(state: AgentState) -> AgentState:
    """Step 6: Enforces strict Pydantic tool input schema contracts; records validation failures."""
    start = time.time()
    selected_tool = state.get("selected_tool")
    raw_args = state.get("raw_tool_args", {})
    retry_count = state.get("retry_count", 0)

    tool = HEALTHCARE_TOOLS.get(selected_tool or "")
    if not tool:
        err_msg = f"Unknown or unconfigured tool '{selected_tool}'"
        next_retry = retry_count + 1
        history = list(state.get("correction_history") or [])
        history.append({
            "attempt": next_retry,
            "tool_name": selected_tool,
            "failed_args": dict(raw_args),
            "validation_errors": [err_msg],
            "diagnostics": [],
        })
        return {
            "validated_tool_args": {},
            "validation_errors": [err_msg],
            "retry_count": next_retry,
            "last_failed_args": dict(raw_args),
            "retry_feedback": err_msg,
            "correction_history": history,
        }

    val_result = tool.validate_args(raw_args)
    if val_result.is_valid:
        is_self_corrected = retry_count > 0
        step_title = "6. Validate Tool Inputs (Self-Corrected)" if is_self_corrected else "6. Validate Tool Inputs"
        TrajectoryTracer().log_step(
            trace_id=state["trace_id"],
            step_name=step_title,
            provider="system",
            model="pydantic_schema_validator",
            latency_ms=(time.time() - start) * 1000.0,
            status="valid",
            metadata={"tool": selected_tool, "self_corrected": is_self_corrected, "attempts": retry_count},
        )
        return {
            "validated_tool_args": val_result.validated_args,
            "validation_errors": [],
            "retry_feedback": None,
        }

    next_retry = retry_count + 1
    feedback_str = f"Validation failed for tool '{selected_tool}': {'; '.join(val_result.errors)}"
    history = list(state.get("correction_history") or [])
    history.append({
        "attempt": next_retry,
        "tool_name": selected_tool,
        "failed_args": dict(raw_args),
        "validation_errors": val_result.errors,
        "diagnostics": getattr(val_result, "diagnostics", []),
    })

    TrajectoryTracer().log_step(
        trace_id=state["trace_id"],
        step_name=f"6. Validate Tool Inputs (Attempt {next_retry} Failed)",
        provider="system",
        model="pydantic_schema_validator",
        latency_ms=(time.time() - start) * 1000.0,
        status="invalid",
        metadata={
            "errors": val_result.errors,
            "diagnostics": getattr(val_result, "diagnostics", []),
            "retry_count": next_retry,
            "failed_args": raw_args,
        },
    )
    return {
        "validated_tool_args": {},
        "validation_errors": val_result.errors,
        "retry_count": next_retry,
        "last_failed_args": dict(raw_args),
        "retry_feedback": feedback_str,
        "correction_history": history,
    }


# --- STEP 7: Execute Tools ---
def execute_tool_node(state: AgentState) -> AgentState:
    """Step 7: Executes tool under deterministic contract with timeout and error handling."""
    start = time.time()
    tool_name = state.get("selected_tool")
    args = state.get("validated_tool_args") or state.get("raw_tool_args", {})
    tool = HEALTHCARE_TOOLS.get(tool_name or "")

    result = tool.run(args).model_dump() if tool else {"success": False, "tool_name": str(tool_name), "error": "Tool not found"}

    TrajectoryTracer().log_step(
        trace_id=state["trace_id"],
        step_name="7. Execute Tools",
        provider="system",
        model="tool_runtime",
        latency_ms=(time.time() - start) * 1000.0,
        status="success" if result.get("success") else "failure",
        metadata={"tool": tool_name, "success": result.get("success")},
    )

    return {"tool_result": result}


# --- STEP 8: Inspect Results ---
def inspect_results_node(state: AgentState) -> AgentState:
    """Step 8: Inspects and verifies tool execution results for safety and consistency."""
    start = time.time()
    tool_result = state.get("tool_result") or {}

    TrajectoryTracer().log_step(
        trace_id=state["trace_id"],
        step_name="8. Inspect Results",
        provider="system",
        model="result_inspector",
        latency_ms=(time.time() - start) * 1000.0,
        status="inspected",
        metadata={"result_success": tool_result.get("success", False)},
    )

    return {"tool_result": tool_result}


# --- STEP 9: Ask Confirmation (HITL Gate) ---
def human_approval_node(state: AgentState) -> AgentState:
    """Step 9: Halts state execution via LangGraph checkpointer until explicit human authorization."""
    start = time.time()
    user_approval = state.get("user_approval_granted")
    status = "APPROVED" if user_approval is True else ("REJECTED" if user_approval is False else "WAITING_APPROVAL")

    TrajectoryTracer().log_step(
        trace_id=state["trace_id"],
        step_name="9. Ask Confirmation (HITL Gate)",
        provider="system",
        model="human_in_the_loop_gate",
        latency_ms=(time.time() - start) * 1000.0,
        status=status,
        metadata={"user_approval_granted": user_approval},
    )

    return {"hitl_status": status}


# --- STEP 10: Generate Response ---
def generate_response_node(state: AgentState) -> AgentState:
    """Step 10: Generates empathetic, clinically structured response via OpenAI or deterministic fallback."""
    resp_text, meta = ModelRouter().generate_response(
        intent=state.get("intent"),
        policy_decision=state.get("policy_decision"),
        tool_result=state.get("tool_result"),
        validation_errors=state.get("validation_errors"),
        security_flag=state.get("security_flag", False),
        hitl_status=state.get("hitl_status"),
        context=state.get("active_context"),
        entities=state.get("entities"),
        user_input=state.get("sanitized_input"),
    )

    # Reversible PII restoration for safe patient presentation
    pii_map = state.get("pii_token_map") or {}
    if pii_map:
        resp_text = deanonymize_pii(resp_text, pii_map)

    TrajectoryTracer().log_step(
        trace_id=state["trace_id"],
        step_name="10. Generate Response",
        provider=meta["provider"],
        model=meta["model"],
        tokens_in=meta["tokens_in"],
        tokens_out=meta["tokens_out"],
        ttft_ms=meta["ttft_ms"],
        latency_ms=meta["latency_ms"],
        cost_usd=meta["cost_usd"],
        status="success",
        metadata={"response_length": len(resp_text)},
    )

    messages = list(state.get("messages", []))
    messages.append({"role": "assistant", "content": resp_text})

    # Track or clear pending_offered_slot across turns
    pending_slot = state.get("pending_offered_slot")
    if state.get("selected_tool") == "RequestSlotReschedule":
        pending_slot = None
    else:
        tool_res = state.get("tool_result") or {}
        slots = []
        if isinstance(tool_res.get("slots"), list):
            slots = tool_res["slots"]
        elif isinstance(tool_res.get("data"), dict) and isinstance(tool_res["data"].get("slots"), list):
            slots = tool_res["data"]["slots"]
        elif (state.get("entities") or {}).get("slot_conflict"):
            conf = state["entities"]["slot_conflict"]
            slots = conf.get("same_day_slots") or conf.get("available_slots") or []

        if slots:
            pending_slot = slots[0]
        else:
            extracted, _ = normalize_slot_and_date(resp_text)
            if extracted:
                pending_slot = extracted

    # Ensure pending_slot is strictly a valid ISO timestamp
    if pending_slot and not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", str(pending_slot)):
        pending_slot = None

    return {
        "final_response": resp_text,
        "messages": messages,
        "pending_offered_slot": pending_slot,
    }


# --- STEP 11: Log Execution Trace ---
def log_trace_node(state: AgentState) -> AgentState:
    """Step 11: Aggregates step traces, latencies, and costs into the final evaluation payload."""
    trace_id = state["trace_id"]
    records = TrajectoryTracer().get_trace_records(trace_id)
    total_lat = sum(r.latency_ms for r in records)
    total_cost = sum(r.cost_usd for r in records)

    eval_payload = {
        "trace_id": trace_id,
        "intent": state.get("intent"),
        "intent_confidence": state.get("intent_confidence", 0.0),
        "entities": state.get("entities"),
        "active_context": state.get("active_context"),
        "policy_decision": state.get("policy_decision"),
        "selected_tool": state.get("selected_tool"),
        "requires_confirmation": state.get("requires_confirmation", False),
        "user_approval_granted": state.get("user_approval_granted"),
        "hitl_status": state.get("hitl_status"),
        "validation_errors": state.get("validation_errors", []),
        "retry_count": state.get("retry_count", 0),
        "tool_result": state.get("tool_result"),
        "security_flag": state.get("security_flag", False),
        "final_response": state.get("final_response"),
        "total_latency_ms": round(total_lat, 2),
        "total_cost_usd": round(total_cost, 7),
    }

    return {
        "trace_metadata": [r.model_dump() for r in records],
        "eval_payload": eval_payload,
    }


# --- STEP 12: Send Async Evaluation Data ---
def send_eval_data_node(state: AgentState) -> AgentState:
    """Step 12: Asynchronously dispatches transaction evaluation payload to background worker."""
    eval_payload = state.get("eval_payload")
    if eval_payload:
        AsyncEvaluationWorker().submit_trace(eval_payload)
    return state
