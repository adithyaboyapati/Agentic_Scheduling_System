"""Workflow state schema and persistent SQLite checkpointer initialization."""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict
from langgraph.checkpoint.sqlite import SqliteSaver


class AgentState(TypedDict, total=False):
    """Explicit LangGraph state schema for the 12-step execution loop."""

    # Chat history and inputs
    messages: List[Dict[str, Any]]
    raw_user_input: str
    sanitized_input: str
    pii_token_map: Dict[str, str]

    # Security status
    security_flag: bool
    security_reason: Optional[str]

    # Clinical Identifiers
    patient_id: Optional[str]
    doctor_id: Optional[str]

    # Step 2: Intent & Extraction
    intent: Optional[str]
    intent_confidence: float
    entities: Dict[str, Any]

    # Step 3: Minimal RAG Context
    active_context: Optional[Dict[str, Any]]

    # Step 4: Policy Decision
    policy_decision: Optional[Dict[str, Any]]

    # Step 5 & 6: Tool Selection, Validation & Self-Correction
    selected_tool: Optional[str]
    raw_tool_args: Dict[str, Any]
    validated_tool_args: Dict[str, Any]
    validation_errors: List[str]
    retry_count: int
    last_failed_args: Optional[Dict[str, Any]]
    retry_feedback: Optional[str]
    correction_history: Optional[List[Dict[str, Any]]]

    # Step 9: Human-in-the-loop (HITL) Gate
    requires_confirmation: bool
    user_approval_granted: Optional[bool]
    hitl_status: Optional[str]  # "PENDING" | "APPROVED" | "REJECTED" | "BYPASSED"

    # Step 7 & 8: Tool Execution & Inspection
    tool_result: Optional[Dict[str, Any]]

    # Step 10: Final Response
    final_response: Optional[str]

    # Multi-turn Context & Pending Slot Offer
    pending_offered_slot: Optional[str]

    # Step 11 & 12: Granular Observability & Evals
    trace_id: str
    trace_metadata: List[Dict[str, Any]]
    eval_payload: Optional[Dict[str, Any]]


def create_sqlite_checkpointer(db_path: str = "checkpoints.db") -> SqliteSaver:
    """Creates a persistent SqliteSaver checkpointer for thread checkpointing across restarts."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    return SqliteSaver(conn)
