"""Unit tests for tool contracts, Pydantic validations, and database mutations."""

import pytest
from src.tools.mock_db import MockHealthcareDB
from src.tools.appointment_tools import (
    GetAppointmentDetailsTool,
    GetAvailableSlotsTool,
    RequestSlotRescheduleTool,
    RequestSlotRescheduleInput,
)


@pytest.fixture(autouse=True)
def reset_db():
    """Ensure clean database state before each test."""
    db = MockHealthcareDB()
    db.reset()
    yield
    db.reset()


def test_get_appointment_details_tool():
    tool = GetAppointmentDetailsTool()
    res = tool.run({"patient_id": "P101", "appointment_id": "APT-201"})

    assert res.success is True
    assert res.data["appointment"]["appointment_id"] == "APT-201"
    assert res.data["appointment"]["doctor_id"] == "DOC1"


def test_get_appointment_details_unauthorized():
    tool = GetAppointmentDetailsTool()
    # P102 trying to view P101's appointment
    res = tool.run({"patient_id": "P102", "appointment_id": "APT-201"})

    assert res.success is False
    assert "Access denied" in res.error


def test_get_available_slots_tool():
    tool = GetAvailableSlotsTool()
    res = tool.run({"doctor_id": "DOC1"})

    assert res.success is True
    assert len(res.data["slots"]) > 0
    assert "2026-09-23T09:00:00" in res.data["slots"]


def test_request_slot_reschedule_tool_success():
    tool = RequestSlotRescheduleTool()
    args = {
        "patient_id": "P101",
        "appointment_id": "APT-201",
        "new_slot_time": "2026-09-23T09:00:00",
        "reason": "Work conflict",
    }
    res = tool.run(args)

    assert res.success is True
    assert res.data["status"] == "RESCHEDULED"
    assert res.data["appointment"]["slot_time"] == "2026-09-23T09:00:00"

    # Verify DB was mutated
    db = MockHealthcareDB()
    apt = db.get_appointment("APT-201")
    assert apt["slot_time"] == "2026-09-23T09:00:00"


def test_request_slot_reschedule_invalid_slot_format():
    tool = RequestSlotRescheduleTool()
    # Invalid date format
    val = tool.validate_args({
        "patient_id": "P101",
        "appointment_id": "APT-201",
        "new_slot_time": "tomorrow at 10am",
    })

    assert val.is_valid is False
    assert any("new_slot_time" in e for e in val.errors)
