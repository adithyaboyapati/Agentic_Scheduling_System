"""LangGraph StateGraph assembly, compilation, and persistent checkpointer integration."""

from __future__ import annotations

import sqlite3
from typing import Optional
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver

from src.storage.state import AgentState
from src.orchestrator.nodes import (
    receive_message_node,
    classify_intent_node,
    retrieve_context_node,
    check_policy_node,
    select_tools_node,
    validate_tool_args_node,
    human_approval_node,
    execute_tool_node,
    inspect_results_node,
    generate_response_node,
    log_trace_node,
    send_eval_data_node,
)
from src.orchestrator.edges import (
    route_after_security,
    route_after_intent,
    route_after_policy,
    route_after_validation,
    route_after_approval,
)


def build_appointment_graph(
    checkpointer: Optional[SqliteSaver] = None,
    db_path: str = "checkpoints.db",
    enable_interrupt: bool = True,
):
    """Assembles and compiles the 12-step LangGraph StateGraph with persistent checkpoints."""
    workflow = StateGraph(AgentState)

    # 1. Register all nodes
    workflow.add_node("receive_message_node", receive_message_node)
    workflow.add_node("classify_intent_node", classify_intent_node)
    workflow.add_node("retrieve_context_node", retrieve_context_node)
    workflow.add_node("check_policy_node", check_policy_node)
    workflow.add_node("select_tools_node", select_tools_node)
    workflow.add_node("validate_tool_args_node", validate_tool_args_node)
    workflow.add_node("human_approval_node", human_approval_node)
    workflow.add_node("execute_tool_node", execute_tool_node)
    workflow.add_node("inspect_results_node", inspect_results_node)
    workflow.add_node("generate_response_node", generate_response_node)
    workflow.add_node("log_trace_node", log_trace_node)
    workflow.add_node("send_eval_data_node", send_eval_data_node)

    # 2. Define Entry Point
    workflow.set_entry_point("receive_message_node")

    # 3. Define Edges and Conditional Edges
    # Step 1 -> Security Routing
    workflow.add_conditional_edges(
        "receive_message_node",
        route_after_security,
        {
            "classify_intent_node": "classify_intent_node",
            "generate_response_node": "generate_response_node",
        },
    )

    # Step 2 -> Intent Routing
    workflow.add_conditional_edges(
        "classify_intent_node",
        route_after_intent,
        {
            "retrieve_context_node": "retrieve_context_node",
            "generate_response_node": "generate_response_node",
        },
    )

    # Step 3 -> Step 4
    workflow.add_edge("retrieve_context_node", "check_policy_node")

    # Step 4 -> Policy Routing
    workflow.add_conditional_edges(
        "check_policy_node",
        route_after_policy,
        {
            "select_tools_node": "select_tools_node",
            "generate_response_node": "generate_response_node",
        },
    )

    # Step 5 -> Step 6
    workflow.add_edge("select_tools_node", "validate_tool_args_node")

    # Step 6 -> Validation Routing (includes self-correction retry loop!)
    workflow.add_conditional_edges(
        "validate_tool_args_node",
        route_after_validation,
        {
            "select_tools_node": "select_tools_node",       # Self-correction loop
            "human_approval_node": "human_approval_node",   # HITL Gate
            "execute_tool_node": "execute_tool_node",       # Direct read tool execution
            "generate_response_node": "generate_response_node", # Retries exhausted
        },
    )

    # Step 9 -> Approval Routing
    workflow.add_conditional_edges(
        "human_approval_node",
        route_after_approval,
        {
            "execute_tool_node": "execute_tool_node",
            "generate_response_node": "generate_response_node",
        },
    )

    # Step 7 -> Step 8
    workflow.add_edge("execute_tool_node", "inspect_results_node")

    # Step 8 -> Step 10
    workflow.add_edge("inspect_results_node", "generate_response_node")

    # Step 10 -> Step 11
    workflow.add_edge("generate_response_node", "log_trace_node")

    # Step 11 -> Step 12
    workflow.add_edge("log_trace_node", "send_eval_data_node")

    # Step 12 -> Finish
    workflow.add_edge("send_eval_data_node", END)

    # 4. Checkpointer Setup
    if checkpointer is None:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        checkpointer = SqliteSaver(conn)

    # 5. Compile Graph with interrupt_before on human approval node
    interrupts = ["human_approval_node"] if enable_interrupt else []
    compiled_app = workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=interrupts,
    )

    return compiled_app
