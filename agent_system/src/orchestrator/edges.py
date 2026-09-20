"""Conditional edges and dynamic routing logic for the 12-step execution loop."""

from __future__ import annotations

import logging
from src.models.schemas import IntentType
from src.storage.state import AgentState

logger = logging.getLogger("GraphEdges")


def route_after_security(state: AgentState) -> str:
    """Routes to rejection if security guardrail flagged prompt injection, else proceeds."""
    if state.get("security_flag"):
        logger.warning("Security threat detected. Bypassing intent and routing to rejection response.")
        return "generate_response_node"
    return "classify_intent_node"


def route_after_intent(state: AgentState) -> str:
    """Routes out-of-scope queries directly to response generation, else to RAG context retrieval."""
    entities = state.get("entities") or {}
    req_patient = entities.get("requested_patient_id") or entities.get("patient_id")
    sess_patient = state.get("patient_id")

    # If cross-tenant access is attempted, it MUST be evaluated and blocked by the policy engine
    if req_patient and sess_patient and req_patient.strip().upper() != sess_patient.strip().upper():
        logger.warning(f"Cross-patient request detected ('{req_patient}' vs '{sess_patient}'). Routing to policy enforcement.")
        return "retrieve_context_node"

    intent = state.get("intent")
    if intent == IntentType.OUT_OF_SCOPE.value:
        logger.info(f"Intent '{intent}' is OUT_OF_SCOPE. Routing directly to response generation.")
        return "generate_response_node"
    return "retrieve_context_node"


def route_after_policy(state: AgentState) -> str:
    """Routes to response if policy check failed (e.g. <24h violation), else to tool selection."""
    decision = state.get("policy_decision") or {}
    if not decision.get("allowed", True):
        logger.info(f"Policy denied action: {decision.get('policy_code')}. Bypassing tools.")
        return "generate_response_node"
    return "select_tools_node"


MAX_RETRIES = 2


def route_after_validation(state: AgentState) -> str:
    """Self-correction dynamic feedback loop: Retries extraction up to MAX_RETRIES on schema errors."""
    val_errors = state.get("validation_errors") or []
    retry_count = state.get("retry_count", 0)

    if val_errors:
        if retry_count < MAX_RETRIES:
            logger.info(
                f"Dynamic Feedback Loop triggered: {val_errors}. Routing Step 6 -> Step 5 for self-correction (attempt {retry_count}/{MAX_RETRIES})."
            )
            return "select_tools_node"
        else:
            logger.warning(
                f"Validation self-correction exhausted ({retry_count}/{MAX_RETRIES} retries). Falling back to response generation."
            )
            return "generate_response_node"

    # Validation succeeded
    if state.get("requires_confirmation", False):
        logger.info("High-risk write operation requires human confirmation. Routing to HITL gate.")
        return "human_approval_node"

    logger.info("Read-only tool validated. Routing directly to tool execution.")
    return "execute_tool_node"


def route_after_approval(state: AgentState) -> str:
    """Routes to tool execution only if user granted approval at the HITL gate."""
    granted = state.get("user_approval_granted")
    if granted is True:
        logger.info("User granted explicit approval. Routing to tool execution.")
        return "execute_tool_node"
    else:
        logger.info("User rejected or withheld approval. Routing directly to response generation.")
        return "generate_response_node"
