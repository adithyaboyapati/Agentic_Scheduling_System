"""Central deterministic policy engine orchestrating clinical and administrative rules."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from src.models.schemas import IntentType, PolicyDecisionResult
from src.policies.authorization import AuthorizationValidator
from src.policies.cancellation_policy import CancellationPolicyValidator
from src.tools.mock_db import MockHealthcareDB


class PolicyEngine:
    """Deterministic policy gatekeeper. Application code is the source of truth."""

    def __init__(self, db: Optional[MockHealthcareDB] = None):
        self.db = db or MockHealthcareDB()

    def evaluate(
        self,
        intent_str: Optional[str],
        patient_id: Optional[str],
        active_context: Optional[Dict[str, Any]],
        entities: Optional[Dict[str, Any]] = None,
    ) -> PolicyDecisionResult:
        """Evaluates permissions, authorization, and clinical rescheduling policies."""
        if not intent_str:
            return PolicyDecisionResult(
                allowed=False,
                requires_confirmation=False,
                policy_code="POLICY_UNKNOWN_INTENT",
                reason="No intent specified for policy evaluation.",
            )

        context = active_context or {}
        apt = context.get("active_appointment")

        # 0. Zero-Trust Tenant Isolation: Intercept cross-patient ID or appointment requests
        req_patient = (entities or {}).get("requested_patient_id") or (entities or {}).get("patient_id")
        if req_patient and patient_id and req_patient.strip().upper() != patient_id.strip().upper():
            return PolicyDecisionResult(
                allowed=False,
                requires_confirmation=False,
                policy_code="POLICY_AUTH_DENIED",
                reason=f"Access Denied: Authenticated as patient '{patient_id}'. You do not have authorization to view or manage records for patient '{req_patient}'.",
            )

        unauth_apt = context.get("unauthorized_target_appointment")
        if unauth_apt:
            target_apt_id = unauth_apt.get("appointment_id")
            return PolicyDecisionResult(
                allowed=False,
                requires_confirmation=False,
                policy_code="POLICY_AUTH_DENIED",
                reason=f"Access Denied: Patient '{patient_id}' does not own appointment '{target_apt_id}'.",
            )

        intent = IntentType(intent_str) if intent_str in IntentType._value2member_map_ else None

        # 1. Read-Only Operations (General inquiries, checking slots)
        if intent in (IntentType.CHECK_AVAILABILITY, IntentType.VIEW_APPOINTMENT):
            # Checking slots doesn't strictly require an existing appointment
            if intent == IntentType.VIEW_APPOINTMENT:
                auth_ok, auth_reason = AuthorizationValidator.evaluate_access(patient_id, apt, self.db)
                if not auth_ok:
                    return PolicyDecisionResult(
                        allowed=False,
                        requires_confirmation=False,
                        policy_code="POLICY_AUTH_DENIED",
                        reason=auth_reason,
                    )

            return PolicyDecisionResult(
                allowed=True,
                requires_confirmation=False,
                policy_code="POLICY_READ_ALLOWED",
                reason="Read-only query compliant with access control policy.",
            )

        # 2. Out of Scope Intent
        if intent == IntentType.OUT_OF_SCOPE:
            return PolicyDecisionResult(
                allowed=False,
                requires_confirmation=False,
                policy_code="POLICY_OUT_OF_SCOPE",
                reason="Requested action is out of scope for clinic scheduling services.",
            )

        # 3. High-Risk Write Operations (Reschedule or Cancel)
        if intent in (IntentType.RESCHEDULE_APPOINTMENT, IntentType.CANCEL_APPOINTMENT):
            # Step A: Validate Authorization
            auth_ok, auth_msg = AuthorizationValidator.evaluate_access(patient_id, apt, self.db)
            if not auth_ok:
                return PolicyDecisionResult(
                    allowed=False,
                    requires_confirmation=False,
                    policy_code="POLICY_AUTH_DENIED",
                    reason=auth_msg,
                )

            if not apt:
                return PolicyDecisionResult(
                    allowed=False,
                    requires_confirmation=False,
                    policy_code="POLICY_NO_APPOINTMENT",
                    reason=f"No active confirmed appointment found for patient '{patient_id}' to reschedule.",
                )

            # Step B: Validate 24-Hour Policy
            ref_time = self.db.reference_time
            apt_time_str = apt.get("slot_time", "")
            policy_ok, hours_rem, policy_msg = CancellationPolicyValidator.evaluate(apt_time_str, ref_time)

            if not policy_ok:
                return PolicyDecisionResult(
                    allowed=False,
                    requires_confirmation=False,
                    policy_code="POLICY_24H_VIOLATION",
                    reason=policy_msg,
                    hours_until_appointment=hours_rem,
                )

            # Step C: Check for redundant reschedule to the exact same slot already booked
            if intent == IntentType.RESCHEDULE_APPOINTMENT:
                target_slot = (entities or {}).get("target_slot")
                if target_slot and apt_time_str:
                    target_clean = str(target_slot).replace(" ", "T").strip()
                    apt_clean = str(apt_time_str).replace(" ", "T").strip()
                    if target_clean == apt_clean or (len(target_clean) >= 16 and len(apt_clean) >= 16 and target_clean[:16] == apt_clean[:16]):
                        doc_name = (context.get("doctor") or {}).get("name") or apt.get("doctor_name", "your physician")
                        return PolicyDecisionResult(
                            allowed=False,
                            requires_confirmation=False,
                            policy_code="POLICY_SAME_SLOT",
                            reason=f"Your appointment is already scheduled for this date and time ({apt_clean}) with {doc_name}. No changes are needed.",
                            hours_until_appointment=hours_rem,
                        )

            # High-risk write: Complies with policy, but MUST require HITL user confirmation!
            return PolicyDecisionResult(
                allowed=True,
                requires_confirmation=True,
                policy_code="POLICY_RESCHEDULE_ELIGIBLE",
                reason=(
                    f"Action approved under clinic policy. {policy_msg} "
                    f"Requires patient confirmation before committing changes."
                ),
                hours_until_appointment=hours_rem,
            )

        return PolicyDecisionResult(
            allowed=False,
            requires_confirmation=False,
            policy_code="POLICY_UNHANDLED",
            reason=f"Unhandled intent '{intent_str}'.",
        )
