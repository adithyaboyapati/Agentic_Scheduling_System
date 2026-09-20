"""In-memory thread-safe mock healthcare database.

Simulates clinical electronic health records (EHR) and appointment management systems.
"""

from __future__ import annotations

import copy
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional


class MockHealthcareDB:
    """Thread-safe simulated clinic database."""

    _instance: Optional[MockHealthcareDB] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> MockHealthcareDB:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(MockHealthcareDB, cls).__new__(cls)
                cls._instance._init_db()
            return cls._instance

    def _init_db(self) -> None:
        """Initializes database state with clinic reference data."""
        self.reference_time = datetime(2026, 9, 19, 0, 0, 0)
        self.doctors: Dict[str, Dict[str, Any]] = {
            "DOC1": {"doctor_id": "DOC1", "name": "Dr. Sarah Chen, MD", "department": "Cardiology", "room": "West Wing 304"},
            "DOC2": {"doctor_id": "DOC2", "name": "Dr. Marcus Vance, MD", "department": "Dermatology", "room": "Clinic Tower 102"},
        }
        self.patients: Dict[str, Dict[str, Any]] = {
            "P101": {"patient_id": "P101", "name": "Alice Walker", "mrn": "MRN90210", "phone": "555-019-2831", "email": "alice.walker@example.com"},
            "P102": {"patient_id": "P102", "name": "Bob Miller", "mrn": "MRN48201", "phone": "555-014-9922", "email": "bob.miller@example.com"},
            "P103": {"patient_id": "P103", "name": "Charlie Davis", "mrn": "MRN77104", "phone": "555-018-4411", "email": "charlie.davis@example.com"},
        }
        self.appointments: Dict[str, Dict[str, Any]] = {
            "APT-201": {
                "appointment_id": "APT-201", "patient_id": "P101", "doctor_id": "DOC1", "doctor_name": "Dr. Sarah Chen, MD",
                "slot_time": "2026-09-22T10:00:00", "status": "CONFIRMED", "reason": "Routine cardiac checkup", "created_at": "2026-09-10T10:00:00",
            },
            "APT-202": {
                "appointment_id": "APT-202", "patient_id": "P102", "doctor_id": "DOC2", "doctor_name": "Dr. Marcus Vance, MD",
                "slot_time": "2026-09-19T06:00:00", "status": "CONFIRMED", "reason": "Skin rash examination", "created_at": "2026-09-12T09:00:00",
            },
        }
        self.available_slots: Dict[str, List[str]] = {
            "DOC1": ["2026-09-23T09:00:00", "2026-09-23T11:30:00", "2026-09-24T14:00:00", "2026-09-25T16:00:00"],
            "DOC2": ["2026-09-20T10:00:00", "2026-09-21T15:00:00", "2026-09-22T11:00:00"],
        }
        self.audit_log: List[Dict[str, Any]] = []

    def reset(self) -> None:
        """Resets the mock database to its pristine state for testing."""
        with self._lock:
            self._init_db()

    def get_patient(self, patient_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            p = self.patients.get(patient_id)
            return copy.deepcopy(p) if p else None

    def get_appointment(self, appointment_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            apt = self.appointments.get(appointment_id)
            return copy.deepcopy(apt) if apt else None

    def get_patient_appointments(self, patient_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [copy.deepcopy(a) for a in self.appointments.values() if a["patient_id"] == patient_id and a["status"] == "CONFIRMED"]

    def get_available_slots(self, doctor_id: str, date_filter: Optional[str] = None) -> List[str]:
        with self._lock:
            slots = self.available_slots.get(doctor_id, [])
            if date_filter:
                slots = [s for s in slots if s.startswith(date_filter)]
            return sorted(slots)

    def reschedule_appointment(
        self, appointment_id: str, patient_id: str, new_slot_time: str, reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """Atomically swaps appointment slot and records an audit log entry."""
        with self._lock:
            if appointment_id not in self.appointments:
                raise ValueError(f"Appointment '{appointment_id}' not found.")
            apt = self.appointments[appointment_id]
            if apt["patient_id"] != patient_id:
                raise PermissionError(f"Patient '{patient_id}' is not authorized to modify appointment '{appointment_id}'.")

            doctor_id = apt["doctor_id"]
            doc_slots = self.available_slots.get(doctor_id, [])
            if new_slot_time not in doc_slots:
                raise ValueError(f"Slot '{new_slot_time}' is not available for doctor '{doctor_id}'.")

            old_slot = apt["slot_time"]
            doc_slots.remove(new_slot_time)
            doc_slots.append(old_slot)
            self.available_slots[doctor_id] = sorted(doc_slots)

            apt["slot_time"] = new_slot_time
            apt["status"] = "CONFIRMED"
            apt["last_modified_at"] = self.reference_time.isoformat()
            if reason:
                apt["reschedule_reason"] = reason

            self.audit_log.append({
                "action": "RESCHEDULE", "appointment_id": appointment_id, "patient_id": patient_id,
                "old_slot": old_slot, "new_slot": new_slot_time, "timestamp": self.reference_time.isoformat(),
            })
            return copy.deepcopy(apt)
