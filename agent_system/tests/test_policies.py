"""Unit tests for deterministic business rules and cancellation policy engine."""

from datetime import datetime
import pytest
from src.tools.mock_db import MockHealthcareDB
from src.policies.cancellation_policy import CancellationPolicyValidator
from src.policies.authorization import AuthorizationValidator
from src.policies.engine import PolicyEngine


@pytest.fixture(autouse=True)
def reset_db():
    db = MockHealthcareDB()
    db.reset()
    yield
    db.reset()


def test_24_hour_cancellation_policy_allowed():
    ref_time = datetime(2026, 9, 19, 0, 0, 0)
    # Appointment is on 2026-09-22T10:00:00 (~78 hours away)
    apt_time = "2026-09-22T10:00:00"
    ok, hours, msg = CancellationPolicyValidator.evaluate(apt_time, ref_time)

    assert ok is True
    assert hours > 24.0
    assert "24-hour advance cancellation policy satisfied" in msg


def test_24_hour_cancellation_policy_denied():
    ref_time = datetime(2026, 9, 19, 0, 0, 0)
    # Appointment is on 2026-09-19T06:00:00 (6 hours away)
    apt_time = "2026-09-19T06:00:00"
    ok, hours, msg = CancellationPolicyValidator.evaluate(apt_time, ref_time)

    assert ok is False
    assert hours == 6.0
    assert "Policy violation" in msg
    assert "at least 24 hours" in msg


def test_authorization_validator():
    db = MockHealthcareDB()
    apt = db.get_appointment("APT-201")  # Owned by P101

    # Authorized owner
    ok1, _ = AuthorizationValidator.evaluate_access("P101", apt, db)
    assert ok1 is True

    # Unauthorized patient
    ok2, msg2 = AuthorizationValidator.evaluate_access("P102", apt, db)
    assert ok2 is False
    assert "does not own appointment" in msg2


def test_policy_engine_reschedule_scenarios():
    engine = PolicyEngine()
    db = MockHealthcareDB()

    # Scenario 1: P101 with appointment 78h in future -> Allowed & requires HITL confirmation
    apt_p101 = db.get_appointment("APT-201")
    context_p101 = {"active_appointment": apt_p101}
    dec1 = engine.evaluate("RESCHEDULE_APPOINTMENT", "P101", context_p101)

    assert dec1.allowed is True
    assert dec1.requires_confirmation is True
    assert dec1.policy_code == "POLICY_RESCHEDULE_ELIGIBLE"

    # Scenario 2: P102 with appointment 6h in future -> Denied due to 24h rule
    apt_p102 = db.get_appointment("APT-202")
    context_p102 = {"active_appointment": apt_p102}
    dec2 = engine.evaluate("RESCHEDULE_APPOINTMENT", "P102", context_p102)

    assert dec2.allowed is False
    assert dec2.requires_confirmation is False
    assert dec2.policy_code == "POLICY_24H_VIOLATION"

    # Scenario 3: P101 requests reschedule to the exact same slot already booked -> POLICY_SAME_SLOT
    dec3 = engine.evaluate(
        "RESCHEDULE_APPOINTMENT",
        "P101",
        context_p101,
        entities={"target_slot": apt_p101["slot_time"]},
    )
    assert dec3.allowed is False
    assert dec3.requires_confirmation is False
    assert dec3.policy_code == "POLICY_SAME_SLOT"
    assert "already scheduled" in dec3.reason.lower()
