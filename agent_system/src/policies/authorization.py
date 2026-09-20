"""Deterministic patient authorization and EHR scope enforcement.

Guarantees tenant isolation: patients can only access and modify their own
confirmed records in the healthcare system.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
from src.tools.mock_db import MockHealthcareDB


def evaluate_patient_access(
    patient_id: Optional[str],
    appointment: Optional[Dict[str, Any]],
    db: Optional[MockHealthcareDB] = None,
) -> Tuple[bool, str]:
    """Validates patient identity and appointment ownership."""
    database = db or MockHealthcareDB()

    if not patient_id:
        return False, "Authorization failure: Patient ID is required to verify identity."

    patient = database.get_patient(patient_id)
    if not patient:
        return False, f"Authorization failure: Patient record '{patient_id}' not found in clinic EHR."

    if appointment:
        owner_id = appointment.get("patient_id")
        if owner_id != patient_id:
            return (
                False,
                f"Authorization failure: Patient '{patient_id}' does not own appointment '{appointment.get('appointment_id')}'.",
            )

    return True, f"Patient '{patient_id}' successfully authorized."


class AuthorizationValidator:
    """Backward-compatible facade for patient authorization verification."""

    @classmethod
    def evaluate_access(
        cls,
        patient_id: Optional[str],
        appointment: Optional[Dict[str, Any]],
        db: Optional[MockHealthcareDB] = None,
    ) -> Tuple[bool, str]:
        return evaluate_patient_access(patient_id, appointment, db)
