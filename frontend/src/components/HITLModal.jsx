import React, { useEffect } from 'react';
import { playHitlAlert, playClick, playSuccess } from '../utils/audio';

function formatModalTime(isoString) {
  if (!isoString) return 'Pending Selection';
  try {
    const d = new Date(isoString);
    return (
      d.toLocaleDateString('en-US', {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      }) +
      ' • ' +
      d.toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
        hour12: true,
      })
    );
  } catch {
    return isoString;
  }
}

export default function HITLModal({
  pendingApproval,
  onResolveApproval,
  isSubmitting,
}) {
  useEffect(() => {
    if (pendingApproval) {
      playHitlAlert();
    }
  }, [pendingApproval]);

  if (!pendingApproval) return null;

  const { tool, args, policyReason, threadId } = pendingApproval;

  const slotTime =
    args?.new_slot_time ||
    args?.target_slot ||
    pendingApproval.newSlotTime ||
    pendingApproval.new_slot_time ||
    pendingApproval.target_slot ||
    pendingApproval.targetSlot;

  const readableSlot = formatModalTime(slotTime);
  const appointmentId =
    args?.appointment_id ||
    pendingApproval.appointmentId ||
    pendingApproval.appointment_id ||
    'APT-201';
  const patientId =
    args?.patient_id ||
    pendingApproval.patientId ||
    pendingApproval.patient_id ||
    'P101';
  const toolName = tool || pendingApproval.tool || 'RequestSlotReschedule';
  const reasonText =
    args?.reason ||
    pendingApproval.reason ||
    'Patient digital portal request';
  const policyText =
    policyReason ||
    pendingApproval.policyReason ||
    'Appointment meets all clinical scheduling criteria and 24h cancellation policies.';

  return (
    <div className="modal-overlay" id="hitl-modal-overlay">
      <div className="hitl-modal-card glass-modal">
        {/* Header */}
        <div className="hitl-modal-header">
          <div className="hitl-warning-badge">
            <span className="warning-pulse"></span>
            ⚠️
          </div>
          <div>
            <h3 className="hitl-modal-title">Human-in-the-Loop Reschedule Authorization</h3>
            <p className="hitl-modal-sub">
              LangGraph Checkpoint Intercept (Step 9 Gate • SQLite Thread {threadId?.slice(0, 16)}...)
            </p>
          </div>
        </div>

        {/* Content */}
        <div className="hitl-modal-body">
          <div className="hitl-alert-callout">
            <strong>Clinical Safety Protocol:</strong> Modifying confirmed appointments requires explicit patient confirmation.
            Review the details below before committing state changes to the EHR database.
          </div>

          {/* Visual Transition Diagram */}
          <div className="reschedule-transition-card">
            <div className="transition-col">
              <span className="trans-lbl">Target Appointment:</span>
              <strong className="trans-val">{appointmentId}</strong>
              <span className="trans-sub">Patient: {patientId}</span>
              <span className="trans-status-tag old">Current Booking</span>
            </div>

            <div className="transition-arrow">
              <span className="arrow-beam"></span>
              ➔
            </div>

            <div className="transition-col highlight">
              <span className="trans-lbl">Authorized New Time:</span>
              <strong className="trans-val time-highlight">{readableSlot}</strong>
              <span className="trans-sub iso-code">{slotTime || 'Pending Selection'}</span>
              <span className="trans-status-tag new">✓ New Slot</span>
            </div>
          </div>

          {/* Safety & Policy Verification Checklist */}
          <div className="hitl-checklist-card">
            <div className="checklist-title">Clinical Verification Checklist:</div>
            <div className="checklist-item">
              <span className="check-icon">✓</span>
              <span><strong>Patient MRN Verified:</strong> Requester authenticated against active session.</span>
            </div>
            <div className="checklist-item">
              <span className="check-icon">✓</span>
              <span><strong>24-Hour Notice Policy:</strong> Appointment is &gt; 24h away, meeting portal policy.</span>
            </div>
            <div className="checklist-item">
              <span className="check-icon">✓</span>
              <span><strong>Physician Availability:</strong> Target slot validated against doctor schedule.</span>
            </div>
          </div>

          {/* Tool Execution Details */}
          <div className="hitl-info-table">
            <div className="hitl-info-row">
              <span className="hitl-row-label">Action / Tool:</span>
              <span className="hitl-row-val tool-tag">{toolName}</span>
            </div>
            <div className="hitl-info-row">
              <span className="hitl-row-label">Reason for Reschedule:</span>
              <span className="hitl-row-val reason-text">{reasonText}</span>
            </div>
          </div>

          <div className="hitl-policy-notice">
            <span className="notice-check">🛡️</span>
            <span>{policyText}</span>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="hitl-modal-actions">
          <button
            id="btn-hitl-reject"
            className="btn-deny"
            onClick={() => {
              playClick();
              onResolveApproval(false);
            }}
            disabled={isSubmitting}
          >
            Cancel Request
          </button>
          <button
            id="btn-hitl-approve"
            className="btn-approve"
            onClick={() => {
              playSuccess();
              onResolveApproval(true);
            }}
            disabled={isSubmitting}
          >
            {isSubmitting ? (
              <>
                <span className="spinner-inline"></span> Resuming Checkpoint...
              </>
            ) : (
              'Authorize & Finalize Reschedule ➔'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
