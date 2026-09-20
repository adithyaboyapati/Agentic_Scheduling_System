"""Deterministic 24-hour advance cancellation and rescheduling policy enforcement.

Ensures clinical schedule stability by strictly requiring a minimum of 24 hours
advance notice before an appointment can be cancelled or rescheduled.
"""

from __future__ import annotations

from datetime import datetime
from typing import Tuple


def evaluate_cancellation_policy(
    appointment_time_str: str,
    reference_time: datetime,
    minimum_advance_hours: float = 24.0,
) -> Tuple[bool, float, str]:
    """Evaluates whether an appointment satisfies the advance notice threshold.

    Returns:
        (is_compliant, hours_remaining, reason_message)
    """
    try:
        apt_time = datetime.fromisoformat(appointment_time_str)
    except Exception as exc:
        return False, 0.0, f"Invalid appointment timestamp format: {exc}"

    delta = apt_time - reference_time
    hours_remaining = delta.total_seconds() / 3600.0

    if hours_remaining < 0:
        return (
            False,
            hours_remaining,
            f"Appointment was scheduled in the past ({abs(hours_remaining):.1f} hours ago). Cannot reschedule past events.",
        )

    if hours_remaining < minimum_advance_hours:
        return (
            False,
            hours_remaining,
            (
                f"Policy violation: Rescheduling requires at least {minimum_advance_hours:.0f} hours advance notice. "
                f"Current appointment starts in {hours_remaining:.1f} hours. Late cancellations must be coordinated "
                f"directly with clinic staff."
            ),
        )

    return (
        True,
        hours_remaining,
        (
            f"24-hour advance cancellation policy satisfied. "
            f"Appointment starts in {hours_remaining:.1f} hours (exceeds {minimum_advance_hours:.0f}h threshold)."
        ),
    )


class CancellationPolicyValidator:
    """Backward-compatible facade for cancellation policy evaluation."""

    MINIMUM_ADVANCE_HOURS: float = 24.0

    @classmethod
    def evaluate(
        cls,
        appointment_time_str: str,
        reference_time: datetime,
    ) -> Tuple[bool, float, str]:
        return evaluate_cancellation_policy(appointment_time_str, reference_time, cls.MINIMUM_ADVANCE_HOURS)
