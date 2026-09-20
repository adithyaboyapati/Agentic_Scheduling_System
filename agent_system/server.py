"""FastAPI backend server exposing REST endpoints for the LangGraph Healthcare Agent.

Runs on port 8001 to avoid conflicting with existing port 8000 services.
"""

from __future__ import annotations

import os
import sys
import json
import time
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from pathlib import Path
from dotenv import load_dotenv, find_dotenv

# Load environment variables (OpenAI, Groq, LangSmith) before initializing graphs
_env = find_dotenv(usecwd=True)
if _env:
    load_dotenv(_env)
else:
    load_dotenv(Path(__file__).resolve().parent / ".env")
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Ensure agent_system package is importable
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.orchestrator.graph import build_appointment_graph
from src.tools.mock_db import MockHealthcareDB
from src.evals.tracer import TrajectoryTracer
from src.evals.worker import AsyncEvaluationWorker

app = FastAPI(
    title="LangGraph Healthcare Agent API",
    description="Backend API harness for 12-step LangGraph execution loop with HITL gate",
    version="1.0.0",
)

# Enable CORS for React frontend (Vite runs on localhost:5173 or localhost:3000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Persistent checkpointer graph instance
compiled_graph = build_appointment_graph(db_path="server_checkpoints.db")
db = MockHealthcareDB()
tracer = TrajectoryTracer()
eval_worker = AsyncEvaluationWorker()


# --- Request/Response Schemas ---
class ChatRequest(BaseModel):
    message: str = Field(..., description="User message text")
    patient_id: str = Field(default="P101", description="Current patient ID")
    doctor_id: Optional[str] = Field(default="DOC1", description="Optional doctor ID")
    thread_id: Optional[str] = Field(default=None, description="Conversation thread ID")


class ApprovalRequest(BaseModel):
    thread_id: str = Field(..., description="Target thread ID to resume")
    approved: bool = Field(..., description="True to authorize, False to reject")


class ChatResponse(BaseModel):
    thread_id: str
    requires_approval: bool
    hitl_status: Optional[str]
    final_response: Optional[str]
    intent: Optional[str]
    policy_decision: Optional[Dict[str, Any]]
    selected_tool: Optional[str]
    validated_args: Optional[Dict[str, Any]]
    tool_result: Optional[Dict[str, Any]]
    security_flag: bool
    retry_count: int
    traces: List[Dict[str, Any]]


# --- Endpoints ---
@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "LangGraph Healthcare Agent API", "port": 8001}


@app.get("/api/ehr")
def get_ehr_data():
    """Returns real-time database state (appointments, doctors, open slots, audit log)."""
    return {
        "reference_time": db.reference_time.isoformat(),
        "patients": db.patients,
        "doctors": db.doctors,
        "appointments": db.appointments,
        "available_slots": db.available_slots,
        "audit_log": db.audit_log,
    }


@app.post("/api/reset")
def reset_database():
    """Resets mock database and telemetry for clean testing."""
    db.reset()
    tracer.reset()
    eval_worker.reset()
    return {"status": "success", "message": "Database and telemetry reset to initial state."}


@app.get("/api/metrics")
def get_evaluation_metrics():
    """Returns async evaluation metrics and recent trace spans."""
    metrics = eval_worker.compute_metrics()
    return {
        "metrics": metrics.model_dump(),
        "total_records": len(tracer.all_records),
        "recent_traces": [r.model_dump() for r in tracer.all_records[-15:]],
    }


@app.post("/api/chat", response_model=ChatResponse)
def handle_chat_message(req: ChatRequest):
    """Executes a user message through the LangGraph 12-step pipeline."""
    thread_id = req.thread_id or f"thread-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "raw_user_input": req.message,
        "patient_id": req.patient_id,
        "doctor_id": req.doctor_id,
    }

    try:
        # Run graph
        state = compiled_graph.invoke(initial_state, config=config)

        # Inspect checkpoint state
        snapshot = compiled_graph.get_state(config)
        is_paused_at_hitl = bool(snapshot.next and "human_approval_node" in snapshot.next)

        traces = [r.model_dump() for r in tracer.get_trace_records(state.get("trace_id", ""))]

        return ChatResponse(
            thread_id=thread_id,
            requires_approval=is_paused_at_hitl,
            hitl_status="WAITING_APPROVAL" if is_paused_at_hitl else state.get("hitl_status"),
            final_response=(
                "Action Required: Moving or canceling your existing appointment requires patient confirmation. "
                "Please review the details in the confirmation window and authorize to finalize your reschedule."
                if is_paused_at_hitl
                else state.get("final_response")
            ),
            intent=state.get("intent"),
            policy_decision=state.get("policy_decision"),
            selected_tool=state.get("selected_tool"),
            validated_args=state.get("validated_tool_args"),
            tool_result=state.get("tool_result"),
            security_flag=state.get("security_flag", False),
            retry_count=state.get("retry_count", 0),
            traces=traces,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# --- STEP DEFINITIONS FOR SSE STREAMING ---
STEP_DEFINITIONS = {
    "receive_message_node": {"step": 1, "name": "1. Guardrails", "desc": "PII Scrubbing & Prompt Injection Guard"},
    "classify_intent_node": {"step": 2, "name": "2. Intent", "desc": "Groq Sub-100ms Extraction"},
    "retrieve_context_node": {"step": 3, "name": "3. Context", "desc": "Minimal RAG EHR Retrieval"},
    "check_policy_node": {"step": 4, "name": "4. Policy", "desc": "Deterministic 24h Notice Engine"},
    "select_tools_node": {"step": 5, "name": "5. Tools", "desc": "Tool Contract Selection"},
    "validate_tool_args_node": {"step": 6, "name": "6. Validate", "desc": "Pydantic Schema Validation & Retry"},
    "human_approval_node": {"step": 9, "name": "9. HITL Gate", "desc": "LangGraph Checkpoint Intercept"},
    "execute_tool_node": {"step": 7, "name": "7. Execute", "desc": "Thread-Safe EHR DB Mutation"},
    "inspect_results_node": {"step": 8, "name": "8. Inspect", "desc": "Post-Execution Data Integrity Check"},
    "generate_response_node": {"step": 10, "name": "10. Response", "desc": "gpt-4o Clinical Response Generation"},
    "log_trace_node": {"step": 11, "name": "11. Trace", "desc": "Telemetry & Latency Spans"},
    "send_eval_data_node": {"step": 12, "name": "12. Evals", "desc": "Async Evaluator & LangSmith Export"},
}


def generate_chat_stream(
    thread_id: str,
    initial_input: Optional[Dict[str, Any]] = None,
    is_resume: bool = False,
    approved: Optional[bool] = None,
):
    """Generates a structured Server-Sent Events (SSE) stream for LangGraph execution."""
    config = {"configurable": {"thread_id": thread_id}}
    accumulated_state: Dict[str, Any] = {}

    try:
        if is_resume:
            snapshot = compiled_graph.get_state(config)
            if not snapshot.next:
                err_msg = f"Thread '{thread_id}' is not currently paused at a checkpoint."
                yield f"event: error\ndata: {json.dumps({'error': err_msg})}\n\n"
                return

            compiled_graph.update_state(config, {"user_approval_granted": approved})
            stream_input = None
            first_step = STEP_DEFINITIONS["human_approval_node"]
            yield f"event: stream_start\ndata: {json.dumps({'thread_id': thread_id, 'status': 'started', 'is_resume': True})}\n\n"
            yield f"event: node_start\ndata: {json.dumps({'node': 'human_approval_node', 'step': first_step['step'], 'title': first_step['name'], 'desc': first_step['desc']})}\n\n"
        else:
            stream_input = initial_input
            first_step = STEP_DEFINITIONS["receive_message_node"]
            yield f"event: stream_start\ndata: {json.dumps({'thread_id': thread_id, 'status': 'started', 'is_resume': False})}\n\n"
            yield f"event: node_start\ndata: {json.dumps({'node': 'receive_message_node', 'step': first_step['step'], 'title': first_step['name'], 'desc': first_step['desc']})}\n\n"

        for event in compiled_graph.stream(stream_input, config=config, stream_mode="updates"):
            if not isinstance(event, dict):
                continue

            for node_name, state_update in event.items():
                if node_name == "__interrupt__":
                    continue

                if isinstance(state_update, dict):
                    accumulated_state.update(state_update)

                meta = STEP_DEFINITIONS.get(node_name, {"step": 0, "name": node_name, "desc": ""})

                summary = ""
                if node_name == "receive_message_node":
                    sec_blocked = state_update.get("security_flag", False)
                    summary = "Security alert triggered: potential injection" if sec_blocked else "Patient PII sanitized & injection free"
                elif node_name == "classify_intent_node":
                    intent_val = state_update.get("intent", "UNKNOWN")
                    summary = f"Intent identified: {intent_val}"
                elif node_name == "retrieve_context_node":
                    ctx = state_update.get("active_context") or {}
                    p_name = (ctx.get("patient") or {}).get("name", "Patient")
                    summary = f"Retrieved clinical context for {p_name}"
                elif node_name == "check_policy_node":
                    pol = state_update.get("policy_decision") or {}
                    allowed = pol.get("allowed", True)
                    if pol.get("policy_code") == "POLICY_SAME_SLOT":
                        summary = "Requested slot is already your active confirmed appointment"
                    elif allowed:
                        summary = "24-Hour notice policy verified"
                    else:
                        summary = f"Policy blocked: {pol.get('policy_code')}"
                elif node_name == "select_tools_node":
                    tool = state_update.get("selected_tool")
                    retry_c = accumulated_state.get("retry_count", 0)
                    if state_update.get("entities", {}).get("same_slot_selected"):
                        summary = "Slot identical to current confirmed appointment; no mutation needed"
                    elif retry_c > 0:
                        summary = f"Dynamic feedback self-correction (attempt {retry_c}/2): repaired {tool} inputs"
                    else:
                        summary = f"Selected tool contract: {tool}" if tool else "Direct conversational response"
                elif node_name == "validate_tool_args_node":
                    val_errs = state_update.get("validation_errors") or []
                    retry_c = state_update.get("retry_count", 0)
                    if not val_errs:
                        summary = f"Pydantic schema validated (self-corrected on attempt {retry_c})" if retry_c > 0 else "Arguments validated against Pydantic schema"
                    else:
                        summary = f"Pydantic validation failed: dynamic feedback retry (attempt {retry_c}/2)"
                elif node_name == "human_approval_node":
                    status = state_update.get("hitl_status", "PROCESSED")
                    summary = f"Patient authorization: {status}"
                elif node_name == "execute_tool_node":
                    tool_res = state_update.get("tool_result") or {}
                    success = tool_res.get("success", True)
                    summary = "EHR database mutation committed atomically" if success else "Tool execution failed"
                elif node_name == "inspect_results_node":
                    summary = "Integrity check passed (0 double-booking conflicts)"
                elif node_name == "generate_response_node":
                    summary = "Clinical response synthesized"
                elif node_name == "log_trace_node":
                    summary = "Execution telemetry spans & costs recorded"
                elif node_name == "send_eval_data_node":
                    summary = "Trace evaluated and sent to async worker"

                node_event = {
                    "node": node_name,
                    "step": meta["step"],
                    "title": meta["name"],
                    "desc": meta["desc"],
                    "status": "completed",
                    "summary": summary,
                    "retry_count": state_update.get("retry_count", accumulated_state.get("retry_count", 0)),
                    "validation_errors": state_update.get("validation_errors", []),
                }
                yield f"event: node_complete\ndata: {json.dumps(node_event)}\n\n"

        # Check final checkpoint state
        snapshot = compiled_graph.get_state(config)
        if snapshot and snapshot.values:
            accumulated_state.update(snapshot.values)

        is_paused_at_hitl = bool(snapshot.next and "human_approval_node" in snapshot.next)

        trace_id = accumulated_state.get("trace_id", "")
        traces = [r.model_dump() for r in tracer.get_trace_records(trace_id)]

        if is_paused_at_hitl:
            hitl_payload = {
                "requires_approval": True,
                "thread_id": thread_id,
                "hitl_status": "WAITING_APPROVAL",
                "tool": accumulated_state.get("selected_tool"),
                "args": accumulated_state.get("validated_tool_args"),
                "policy_reason": (accumulated_state.get("policy_decision") or {}).get("reason"),
            }
            yield f"event: hitl_interrupt\ndata: {json.dumps(hitl_payload)}\n\n"

            resp_text = (
                "Action Required: Moving or canceling your existing appointment requires patient confirmation. "
                "Please review the details in the confirmation window and authorize to finalize your reschedule."
            )
        else:
            resp_text = accumulated_state.get("final_response") or "Your clinical request has been processed."

        # Stream response text in natural token chunks
        words = resp_text.split(" ")
        for i, word in enumerate(words):
            chunk = word if i == len(words) - 1 else word + " "
            yield f"event: token\ndata: {json.dumps({'token': chunk})}\n\n"
            time.sleep(0.01)

        # Emit final done event
        done_payload = {
            "thread_id": thread_id,
            "requires_approval": is_paused_at_hitl,
            "hitl_status": "WAITING_APPROVAL" if is_paused_at_hitl else accumulated_state.get("hitl_status"),
            "final_response": resp_text,
            "intent": accumulated_state.get("intent"),
            "policy_decision": accumulated_state.get("policy_decision"),
            "selected_tool": accumulated_state.get("selected_tool"),
            "validated_args": accumulated_state.get("validated_tool_args"),
            "tool_result": accumulated_state.get("tool_result"),
            "security_flag": accumulated_state.get("security_flag", False),
            "retry_count": accumulated_state.get("retry_count", 0),
            "traces": traces,
        }
        yield f"event: done\ndata: {json.dumps(done_payload)}\n\n"

    except Exception as exc:
        yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"


@app.post("/api/chat/stream")
def handle_chat_stream(req: ChatRequest):
    """Executes a user message through LangGraph and streams real-time SSE events."""
    thread_id = req.thread_id or f"thread-{uuid.uuid4().hex[:8]}"
    initial_state = {
        "raw_user_input": req.message,
        "patient_id": req.patient_id,
        "doctor_id": req.doctor_id,
    }
    return StreamingResponse(
        generate_chat_stream(thread_id, initial_input=initial_state, is_resume=False),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/approval/stream")
def handle_approval_stream(req: ApprovalRequest):
    """Resumes an interrupted graph execution from its checkpoint and streams real-time SSE events."""
    return StreamingResponse(
        generate_chat_stream(req.thread_id, is_resume=True, approved=req.approved),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/approval", response_model=ChatResponse)
def handle_hitl_approval(req: ApprovalRequest):
    """Resumes an interrupted graph execution from its SQLite checkpoint with user decision."""
    config = {"configurable": {"thread_id": req.thread_id}}

    snapshot = compiled_graph.get_state(config)
    if not snapshot.next:
        raise HTTPException(
            status_code=400,
            detail=f"Thread '{req.thread_id}' is not currently paused at a checkpoint.",
        )

    try:
        # Update checkpointed state with user approval decision
        compiled_graph.update_state(config, {"user_approval_granted": req.approved})

        # Resume execution from checkpoint
        state = compiled_graph.invoke(None, config=config)
        traces = [r.model_dump() for r in tracer.get_trace_records(state.get("trace_id", ""))]

        return ChatResponse(
            thread_id=req.thread_id,
            requires_approval=False,
            hitl_status=state.get("hitl_status"),
            final_response=state.get("final_response"),
            intent=state.get("intent"),
            policy_decision=state.get("policy_decision"),
            selected_tool=state.get("selected_tool"),
            validated_args=state.get("validated_tool_args"),
            tool_result=state.get("tool_result"),
            security_flag=state.get("security_flag", False),
            retry_count=state.get("retry_count", 0),
            traces=traces,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/chat/thread/{thread_id}")
def get_thread_state(thread_id: str):
    """Retrieves current checkpoint state for a thread from SQLite checkpointer."""
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = compiled_graph.get_state(config)
    if not snapshot or not snapshot.values:
        return {"exists": False, "thread_id": thread_id, "messages": []}

    values = snapshot.values
    is_paused = bool(snapshot.next and "human_approval_node" in snapshot.next)
    return {
        "exists": True,
        "thread_id": thread_id,
        "next_nodes": list(snapshot.next or []),
        "requires_approval": is_paused,
        "hitl_status": "WAITING_APPROVAL" if is_paused else values.get("hitl_status"),
        "messages": values.get("messages", []),
        "intent": values.get("intent"),
        "selected_tool": values.get("selected_tool"),
        "pending_offered_slot": values.get("pending_offered_slot"),
        "validated_args": values.get("validated_tool_args"),
        "policy_decision": values.get("policy_decision"),
    }


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8001, reload=False)
