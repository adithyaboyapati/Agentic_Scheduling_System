"""Concrete tool implementations for appointment inspection, slot querying, and rescheduling."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, field_validator

from src.tools.base import BaseHealthcareTool
from src.tools.mock_db import MockHealthcareDB


# --------------------------------------------------------------------------
# 1. Read-Only: GetAppointmentDetails
# --------------------------------------------------------------------------
class GetAppointmentDetailsInput(BaseModel):
    patient_id: str = Field(..., description="Patient ID, e.g. P101", pattern=r"^P\d{3}$")
    appointment_id: Optional[str] = Field(default=None, description="Optional appointment ID, e.g. APT-201")


class GetAppointmentDetailsTool(BaseHealthcareTool):
    name = "GetAppointmentDetails"
    description = "Retrieve current appointment details for a patient."
    is_read_only = True
    requires_elevation = False
    args_schema = GetAppointmentDetailsInput

    def _execute(self, args: GetAppointmentDetailsInput) -> Dict[str, Any]:
        db = MockHealthcareDB()
        if args.appointment_id:
            apt = db.get_appointment(args.appointment_id)
            if not apt:
                raise ValueError(f"Appointment '{args.appointment_id}' not found.")
            if apt["patient_id"] != args.patient_id:
                raise PermissionError("Access denied: You can only view your own appointments.")
            return {"appointment": apt}

        apts = db.get_patient_appointments(args.patient_id)
        if not apts:
            return {"message": f"No confirmed appointments found for patient {args.patient_id}."}
        return {"appointment": apts[0], "all_appointments": apts}


# --------------------------------------------------------------------------
# 2. Read-Only: GetAvailableSlots
# --------------------------------------------------------------------------
class GetAvailableSlotsInput(BaseModel):
    doctor_id: str = Field(..., description="Doctor ID, e.g. DOC1 or DOC2", pattern=r"^DOC\d+$")
    date_filter: Optional[str] = Field(default=None, description="Optional date prefix (YYYY-MM-DD)")

    @field_validator("date_filter")
    @classmethod
    def validate_date_filter(cls, v: Optional[str]) -> Optional[str]:
        if v and not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError("date_filter must be in YYYY-MM-DD format.")
        return v


class GetAvailableSlotsTool(BaseHealthcareTool):
    name = "GetAvailableSlots"
    description = "Fetch open appointment slots for a specified physician."
    is_read_only = True
    requires_elevation = False
    args_schema = GetAvailableSlotsInput

    def _execute(self, args: GetAvailableSlotsInput) -> Dict[str, Any]:
        db = MockHealthcareDB()
        slots = db.get_available_slots(args.doctor_id, args.date_filter)
        return {
            "doctor_id": args.doctor_id,
            "slots": slots,
            "total_slots": len(slots),
        }


# --------------------------------------------------------------------------
# 3. High-Risk Write: RequestSlotReschedule
# --------------------------------------------------------------------------
class RequestSlotRescheduleInput(BaseModel):
    patient_id: str = Field(..., description="Patient ID, e.g. P101", pattern=r"^P\d{3}$")
    appointment_id: str = Field(..., description="Appointment ID, e.g. APT-201", pattern=r"^APT-\d{3}$")
    new_slot_time: str = Field(..., description="Desired slot timestamp in ISO format, e.g. 2026-09-23T11:30:00")
    reason: Optional[str] = Field(default=None, max_length=200, description="Optional medical or scheduling reason")

    @field_validator("new_slot_time")
    @classmethod
    def validate_iso_slot(cls, v: str) -> str:
        if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", v):
            raise ValueError("new_slot_time must be a valid ISO timestamp: YYYY-MM-DDTHH:MM:SS")
        return v


class RequestSlotRescheduleTool(BaseHealthcareTool):
    name = "RequestSlotReschedule"
    description = "Reschedule a confirmed appointment to a new open slot. Modifies EHR records."
    is_read_only = False
    requires_elevation = True
    args_schema = RequestSlotRescheduleInput

    def _execute(self, args: RequestSlotRescheduleInput) -> Dict[str, Any]:
        db = MockHealthcareDB()
        updated = db.reschedule_appointment(
            appointment_id=args.appointment_id,
            patient_id=args.patient_id,
            new_slot_time=args.new_slot_time,
            reason=args.reason,
        )
        return {
            "status": "RESCHEDULED",
            "appointment": updated,
            "confirmation_code": f"CONF-{updated['appointment_id']}-{updated['slot_time']}",
        }


# Unified Registry
HEALTHCARE_TOOLS: Dict[str, BaseHealthcareTool] = {
    GetAppointmentDetailsTool.name: GetAppointmentDetailsTool(),
    GetAvailableSlotsTool.name: GetAvailableSlotsTool(),
    RequestSlotRescheduleTool.name: RequestSlotRescheduleTool(),
}
