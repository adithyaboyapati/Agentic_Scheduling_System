"""Automated tests for the Pydantic Validation Self-Correction Dynamic Feedback Loop."""

import sqlite3
import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from src.orchestrator.graph import build_appointment_graph
from src.evals.tracer import TrajectoryTracer
from src.evals.worker import AsyncEvaluationWorker
from src.models.router import ModelRouter


def test_self_correction_malformed_slot_timestamp():
    """Validates that a non-standard slot timestamp '2026-09-24_14:00:00' fails Step 6, triggers self-correction, and is repaired to ISO format."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    app = build_appointment_graph(checkpointer=checkpointer)

    thread_config = {"configurable": {"thread_id": "thread-test-iso-repair"}}
    initial_state = {
        "raw_user_input": "Please reschedule appointment APT-201 to slot 2026-09-24_14:00:00",
        "patient_id": "P101",
    }

    # Step 6 fails Pydantic validation -> Step 5 self-corrects -> Step 6 passes -> pauses at HITL gate
    app.invoke(initial_state, config=thread_config)

    snapshot = app.get_state(thread_config)
    assert snapshot.next == ("human_approval_node",)
    assert snapshot.values.get("retry_count", 0) == 1

    validated_args = snapshot.values.get("validated_tool_args", {})
    assert validated_args.get("appointment_id") == "APT-201"
    assert validated_args.get("new_slot_time") == "2026-09-24T14:00:00"

    history = snapshot.values.get("correction_history", [])
    assert len(history) >= 1
    assert history[0]["tool_name"] == "RequestSlotReschedule"
    assert any("new_slot_time" in err for err in history[0]["validation_errors"])


def test_self_correction_slot_time_missing_seconds():
    """Validates that a timestamp missing seconds ('2026-09-24T14:00') triggers self-correction and adds seconds."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    app = build_appointment_graph(checkpointer=checkpointer)

    thread_config = {"configurable": {"thread_id": "thread-test-sec-repair"}}
    initial_state = {
        "raw_user_input": "Reschedule appointment APT-201 to slot 2026-09-24T14:00",
        "patient_id": "P101",
    }

    app.invoke(initial_state, config=thread_config)

    snapshot = app.get_state(thread_config)
    assert snapshot.next == ("human_approval_node",)
    assert snapshot.values.get("retry_count", 0) == 1

    validated_args = snapshot.values.get("validated_tool_args", {})
    assert validated_args.get("appointment_id") == "APT-201"
    assert validated_args.get("new_slot_time") == "2026-09-24T14:00:00"


def test_self_correction_date_filter_format():
    """Validates that underscored date filter 2026_09_24 for GetAvailableSlots is repaired to YYYY-MM-DD."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    app = build_appointment_graph(checkpointer=checkpointer)

    thread_config = {"configurable": {"thread_id": "thread-test-date-filter-repair"}}
    initial_state = {
        "raw_user_input": "Check open slots for Dr. Chen on date 2026_09_24",
        "patient_id": "P101",
        "doctor_id": "DOC1",
    }

    final_state = app.invoke(initial_state, config=thread_config)

    # Read-only tool completes without HITL pause
    assert final_state.get("final_response") is not None
    assert final_state.get("retry_count", 0) == 1
    assert final_state.get("validated_tool_args", {}).get("date_filter") == "2026-09-24"
    assert final_state.get("tool_result", {}).get("success") is True


def test_self_correction_bounded_exhaustion():
    """Verifies that completely non-repairable inputs exhaust retries at exactly 2 and fallback."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    app = build_appointment_graph(checkpointer=checkpointer)

    thread_config = {"configurable": {"thread_id": "thread-test-exhaustion"}}
    initial_state = {
        "raw_user_input": "Check available slots for Dr. Chen on date completely_unfixable_xyz",
        "patient_id": "P101",
        "doctor_id": "DOC1",
    }

    final_state = app.invoke(initial_state, config=thread_config)

    assert final_state.get("retry_count") == 2
    assert final_state.get("final_response") is not None
    response_lower = final_state.get("final_response", "").lower()
    assert any(w in response_lower for w in ["issue", "error", "unable", "sorry", "cannot"])


def test_self_correction_telemetry_and_metrics():
    """Verifies that telemetry traces capture the repair spans and worker computes recovery rate."""
    tracer = TrajectoryTracer()
    eval_worker = AsyncEvaluationWorker()
    tracer.reset()
    eval_worker.reset()

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    app = build_appointment_graph(checkpointer=checkpointer)

    thread_config = {"configurable": {"thread_id": "thread-test-telemetry"}}
    initial_state = {
        "raw_user_input": "Reschedule appointment APT-201 to slot invalid_time",
        "patient_id": "P101",
    }

    app.invoke(initial_state, config=thread_config)
    snapshot = app.get_state(thread_config)
    trace_id = snapshot.values.get("trace_id")

    records = tracer.get_trace_records(trace_id)
    step_names = [r.step_name for r in records]

    # Verify that the failure, repair, and self-corrected steps were traced
    assert any("Attempt 1 Failed" in name for name in step_names)
    assert any("Self-Correction Repair" in name for name in step_names)
    assert any("Self-Corrected" in name for name in step_names)

    # Verify AsyncEvaluationWorker metrics
    metrics = eval_worker.compute_metrics()
    assert metrics.self_correction_recovery_rate >= 0.0
