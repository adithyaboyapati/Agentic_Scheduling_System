"""Decoupled context memory and minimal RAG retrieval.

Retrieves strictly the necessary patient and doctor clinical context
instead of dumping the entire history into the model context window.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from src.tools.mock_db import MockHealthcareDB


class ContextRetriever:
    """Minimal context RAG retriever for healthcare workflows."""

    def __init__(self, db: Optional[MockHealthcareDB] = None):
        self.db = db or MockHealthcareDB()

    def retrieve_context(
        self,
        patient_id: Optional[str],
        doctor_id: Optional[str] = None,
        appointment_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetches minimal, high-signal clinical records for the current transaction."""
        context: Dict[str, Any] = {
            "reference_time": self.db.reference_time.isoformat(),
            "patient": None,
            "active_appointment": None,
            "doctor": None,
            "available_slots": [],
        }

        # 1. Retrieve Patient Demographics (minimal)
        if patient_id:
            patient = self.db.get_patient(patient_id)
            if patient:
                context["patient"] = {
                    "patient_id": patient["patient_id"],
                    "name": patient["name"],
                    "mrn": patient["mrn"],
                }

            # 2. Retrieve Active Appointment (Enforcing tenant boundary)
            if appointment_id:
                clean_apt_id = appointment_id
                if not clean_apt_id.startswith("APT-"):
                    digits = re.findall(r"\d{3}", clean_apt_id)
                    if digits:
                        clean_apt_id = f"APT-{digits[0]}"
                apt = self.db.get_appointment(clean_apt_id) or self.db.get_appointment(appointment_id)
                if apt:
                    if apt.get("patient_id") == patient_id:
                        context["active_appointment"] = apt
                    else:
                        context["unauthorized_target_appointment"] = {
                            "appointment_id": apt.get("appointment_id"),
                            "patient_id": apt.get("patient_id"),
                        }
                else:
                    patient_apts = self.db.get_patient_appointments(patient_id)
                    if patient_apts:
                        context["active_appointment"] = patient_apts[0]
            else:
                patient_apts = self.db.get_patient_appointments(patient_id)
                if patient_apts:
                    context["active_appointment"] = patient_apts[0]

        # 3. Retrieve Doctor Details & Open Slots
        effective_doctor_id = doctor_id
        if not effective_doctor_id and context.get("active_appointment"):
            effective_doctor_id = context["active_appointment"].get("doctor_id")

        if effective_doctor_id:
            doc = self.db.doctors.get(effective_doctor_id)
            if doc:
                context["doctor"] = {
                    "doctor_id": doc["doctor_id"],
                    "name": doc["name"],
                    "department": doc["department"],
                }
                # Limit to top 5 available slots to keep context concise
                all_slots = self.db.get_available_slots(effective_doctor_id)
                context["available_slots"] = all_slots[:5]

        return context
