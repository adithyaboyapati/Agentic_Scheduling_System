import React, { useState, useEffect } from 'react';
import { playClick, playSuccess } from '../utils/audio';

function formatFullDate(isoString) {
  if (!isoString) return 'Pending Date';
  try {
    const date = new Date(isoString);
    return date.toLocaleDateString('en-US', {
      weekday: 'long',
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  } catch {
    return isoString.split('T')[0];
  }
}

function formatTimeOnly(isoString) {
  if (!isoString) return '--:--';
  try {
    const date = new Date(isoString);
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: true,
    });
  } catch {
    return isoString.split('T')[1] || isoString;
  }
}

function getRelativeTimeNotice(isoString, refTimeStr) {
  try {
    const slotDate = new Date(isoString);
    const refDate = refTimeStr ? new Date(refTimeStr) : new Date('2026-09-19T00:00:00');
    const diffHours = (slotDate - refDate) / (1000 * 60 * 60);

    if (diffHours <= 0) return 'Past Appointment';
    if (diffHours < 24) return `In ${Math.round(diffHours)} hours (Under 24h notice)`;
    const diffDays = Math.round(diffHours / 24);
    return `In ${diffDays} days (${Math.round(diffHours)}h away)`;
  } catch {
    return 'Upcoming';
  }
}

function groupSlotsByDate(slots) {
  const map = {};
  (slots || []).forEach((slot) => {
    const dateKey = slot.split('T')[0];
    if (!map[dateKey]) map[dateKey] = [];
    map[dateKey].push(slot);
  });
  return map;
}

export default function EHRBoard({
  ehrData,
  activePatientId,
  onSelectSlot,
  onInstantReschedule,
  activeTab,
  setActiveTab,
}) {
  const [selectedSlot, setSelectedSlot] = useState(null);
  const [showClinicalNotes, setShowClinicalNotes] = useState(false);
  const [selectedDayFilter, setSelectedDayFilter] = useState('ALL');
  const [auditFilter, setAuditFilter] = useState('ALL'); // 'ALL' or 'PATIENT'

  // STRICT MULTI-TENANT RESET: Clear ephemeral selection when active patient switches
  useEffect(() => {
    setSelectedSlot(null);
    setShowClinicalNotes(false);
    setSelectedDayFilter('ALL');
  }, [activePatientId]);

  if (!ehrData) {
    return (
      <div className="ehr-card glass-panel">
        <div className="ehr-header">
          <h2 className="section-title">🏥 Patient Electronic Health Record</h2>
        </div>
        <p style={{ color: 'var(--text-muted)', padding: '20px 0' }}>Loading clinic records...</p>
      </div>
    );
  }

  // Multi-Tenant Isolation: Strictly filter appointments for the active patient
  const patientAppointments = Object.values(ehrData.appointments || {}).filter(
    (apt) => apt.patient_id === activePatientId
  );

  const activePatient = ehrData.patients?.[activePatientId] || {
    patient_id: activePatientId,
    name: activePatientId === 'P101' ? 'Alice Walker' : 'Bob Miller',
    mrn: activePatientId === 'P101' ? 'MRN90210' : 'MRN48201',
    phone: '555-019-2831',
  };

  // Primary physician and slots based on patient
  const isP101 = activePatientId === 'P101';
  const doctorId = isP101 ? 'DOC1' : 'DOC2';
  const doctor = ehrData.doctors?.[doctorId] || {
    name: isP101 ? 'Dr. Sarah Chen, MD' : 'Dr. Marcus Vance, MD',
    department: isP101 ? 'Cardiology' : 'Dermatology',
    room: isP101 ? 'West Wing 304' : 'Clinic Tower 102',
  };

  const availableSlots = ehrData.available_slots?.[doctorId] || [];
  const groupedSlots = groupSlotsByDate(availableSlots);
  const distinctDays = Object.keys(groupedSlots);

  // Filter slots if a specific day is selected
  const filteredGroupedSlots =
    selectedDayFilter === 'ALL'
      ? groupedSlots
      : { [selectedDayFilter]: groupedSlots[selectedDayFilter] || [] };

  const auditEntries = (ehrData.audit_log || []).slice().reverse();

  const handleSlotClick = (slot) => {
    playClick();
    setSelectedSlot(slot);
    if (onSelectSlot) {
      onSelectSlot(slot);
    }
  };

  const handleInstantBook = (slot) => {
    playSuccess();
    if (onInstantReschedule) {
      onInstantReschedule(slot);
    }
  };

  return (
    <div className="ehr-card glass-panel">
      {/* Top Header with Tab Switcher */}
      <div className="ehr-header-wrapper">
        <div className="ehr-header">
          <div>
            <h2 className="section-title">
              <span>🏥 Patient Health Record</span>
            </h2>
            <div className="ehr-patient-subline">
              Active Record: <strong style={{ color: 'var(--cyan-primary)' }}>{activePatient.name}</strong> • ID: {activePatient.patient_id} • MRN: {activePatient.mrn}
            </div>
          </div>
          <span className="live-sync-pill">
            <span className="live-dot"></span> Live Synced
          </span>
        </div>

        {/* Multi-View Subnav Tabs */}
        <div className="portal-tab-bar">
          <button
            id="tab-btn-records"
            className={`portal-tab-btn ${activeTab === 'records' ? 'active' : ''}`}
            onClick={() => {
              playClick();
              setActiveTab('records');
            }}
          >
            <span>📅 Appointment & Open Slots</span>
            <span className="tab-badge">{availableSlots.length}</span>
          </button>
          <button
            id="tab-btn-pipeline"
            className={`portal-tab-btn ${activeTab === 'pipeline' ? 'active' : ''}`}
            onClick={() => {
              playClick();
              setActiveTab('pipeline');
            }}
          >
            <span>⚡ 12-Step Loop & Telemetry</span>
          </button>
          <button
            id="tab-btn-audit"
            className={`portal-tab-btn ${activeTab === 'audit' ? 'active' : ''}`}
            onClick={() => {
              playClick();
              setActiveTab('audit');
            }}
          >
            <span>📜 EHR Audit Trail</span>
            {auditEntries.length > 0 && <span className="tab-badge green">{auditEntries.length}</span>}
          </button>
        </div>
      </div>

      {/* TAB 1: Main Health Record & Interactive Calendar */}
      {activeTab === 'records' && (
        <>
          {/* Hero Scheduled Appointment Card */}
          <div className="appointment-hero-section">
            <div className="section-subtitle">
              <span>Upcoming Scheduled Appointment</span>
              <span className="count-pill">{patientAppointments.length} Active</span>
            </div>

            {patientAppointments.length === 0 ? (
              <div className="no-appointment-box">
                <span className="empty-icon">📅</span>
                <p>No confirmed appointments on file for {activePatient.name}.</p>
              </div>
            ) : (
              patientAppointments.map((apt) => {
                const isEligible24h = apt.appointment_id === 'APT-201';
                const formattedDate = formatFullDate(apt.slot_time);
                const formattedTime = formatTimeOnly(apt.slot_time);
                const relativeNotice = getRelativeTimeNotice(apt.slot_time, ehrData.reference_time);

                return (
                  <div
                    key={apt.appointment_id}
                    id={`appointment-card-${apt.appointment_id}`}
                    className="appointment-hero-card"
                  >
                    {/* Top Bar: ID, Physician, & Status */}
                    <div className="hero-card-header">
                      <div className="apt-id-group">
                        <span className="apt-id-badge">{apt.appointment_id}</span>
                        <span className="apt-doctor-badge">
                          👨‍⚕️ {apt.doctor_name || doctor.name}
                        </span>
                        <span className="doctor-dept-pill">{doctor.department}</span>
                      </div>
                      <div className="status-with-countdown">
                        <span className="countdown-pill">{relativeNotice}</span>
                        <span className={`status-badge-hero ${apt.status.toLowerCase()}`}>
                          ● {apt.status}
                        </span>
                      </div>
                    </div>

                    {/* Date & Time Display with visual calendar badge */}
                    <div className="hero-time-container">
                      <div className="hero-calendar-icon">
                        <span className="cal-month">
                          {new Date(apt.slot_time).toLocaleString('en-US', { month: 'short' }).toUpperCase()}
                        </span>
                        <span className="cal-day">
                          {new Date(apt.slot_time).getDate()}
                        </span>
                      </div>
                      <div className="hero-time-details">
                        <div className="hero-date-str">{formattedDate}</div>
                        <div className="hero-time-str">
                          <span className="time-clock-icon">🕒</span>
                          <strong id={`slot-time-${apt.appointment_id}`}>{formattedTime}</strong>
                          <span className="time-iso-tag">({apt.slot_time})</span>
                        </div>
                      </div>
                    </div>

                    {/* Clinical Context & Room */}
                    <div className="hero-clinical-meta">
                      <div className="meta-item">
                        <span className="meta-label">Location / Room:</span>
                        <span className="meta-value">{doctor.room || 'Main Clinic Tower'}</span>
                      </div>
                      <div className="meta-item">
                        <span className="meta-label">Reason for Visit:</span>
                        <span className="meta-value">{apt.reason || 'Clinical Consultation'}</span>
                      </div>
                    </div>

                    {/* Policy Compliance Pill */}
                    <div className={`policy-notice-pill ${isEligible24h ? 'eligible' : 'violation'}`}>
                      {isEligible24h ? (
                        <>
                          <span className="policy-icon">✓</span>
                          <span>
                            <strong>24-Hour Notice Satisfied:</strong> Appointment is scheduled &gt; 24h in advance. Reschedule permitted via portal with HITL approval.
                          </span>
                        </>
                      ) : (
                        <>
                          <span className="policy-icon">⚠️</span>
                          <span>
                            <strong>&lt; 24-Hour Policy Notice:</strong> Under 24h cancellation window. Same-day modifications require clinic front-desk authorization.
                          </span>
                        </>
                      )}
                    </div>

                    {/* Quick Appointment Actions */}
                    <div className="hero-quick-actions">
                      <button
                        className="hero-action-btn primary"
                        onClick={() => {
                          playClick();
                          const el = document.getElementById('slots-browser-section');
                          el?.scrollIntoView({ behavior: 'smooth' });
                        }}
                        title="Browse available physician openings below"
                      >
                        🗓️ Browse Open Slots
                      </button>
                      <button
                        className="hero-action-btn secondary"
                        onClick={() => {
                          playClick();
                          setShowClinicalNotes(!showClinicalNotes);
                        }}
                        title="Toggle clinical appointment prep details"
                      >
                        {showClinicalNotes ? '▲ Hide Prep Notes' : '📋 Visit Prep Notes'}
                      </button>
                    </div>

                    {/* Expandable Clinical Notes */}
                    {showClinicalNotes && (
                      <div className="clinical-prep-notes">
                        <div className="prep-title">🩺 Pre-Visit Patient Instructions:</div>
                        <ul className="prep-list">
                          <li>Please arrive 15 minutes before your scheduled slot for vitals intake.</li>
                          <li>Bring your current photo ID, insurance card, and list of medications.</li>
                          <li>If fasting is requested for bloodwork, avoid caloric intake 8 hours prior.</li>
                          <li>Need emergency assistance? Call 911 or visit the nearest emergency room.</li>
                        </ul>
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>

          {/* Interactive Available Slots Calendar Browser */}
          <div className="slots-browser-section" id="slots-browser-section">
            <div className="section-subtitle">
              <span>{doctor.name} Available Openings</span>
              <span className="count-pill">{availableSlots.length} Slots</span>
            </div>

            {/* Day Filter Chips Bar */}
            {distinctDays.length > 0 && (
              <div className="day-filter-bar">
                <button
                  className={`day-filter-chip ${selectedDayFilter === 'ALL' ? 'active' : ''}`}
                  onClick={() => {
                    playClick();
                    setSelectedDayFilter('ALL');
                  }}
                >
                  All Days ({availableSlots.length})
                </button>
                {distinctDays.map((day) => {
                  const dObj = new Date(day + 'T00:00:00');
                  const shortDay = dObj.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
                  return (
                    <button
                      key={day}
                      className={`day-filter-chip ${selectedDayFilter === day ? 'active' : ''}`}
                      onClick={() => {
                        playClick();
                        setSelectedDayFilter(day);
                      }}
                    >
                      {shortDay} ({groupedSlots[day]?.length || 0})
                    </button>
                  );
                })}
              </div>
            )}

            <p className="slots-help-text">
              Click any slot to select and trigger 1-click rescheduling through the 12-step graph:
            </p>

            {Object.keys(filteredGroupedSlots).length === 0 ? (
              <div className="no-slots-box">No open slots available for this physician.</div>
            ) : (
              <div className="calendar-groups-list">
                {Object.entries(filteredGroupedSlots).map(([dateKey, slots]) => {
                  const dayLabel = formatFullDate(dateKey);

                  return (
                    <div key={dateKey} className="calendar-day-group">
                      <div className="day-group-header">
                        <span className="day-calendar-pin">📅</span>
                        <span className="day-label-text">{dayLabel}</span>
                        <span className="day-slots-count">{slots.length} available</span>
                      </div>
                      <div className="day-slots-grid">
                        {slots.map((slot, idx) => {
                          const timeLabel = formatTimeOnly(slot);
                          const isSelected = selectedSlot === slot;

                          return (
                            <button
                              key={idx}
                              id={`slot-btn-${slot.replace(/[:T-]/g, '')}`}
                              className={`interactive-slot-chip ${isSelected ? 'selected' : ''}`}
                              onClick={() => handleSlotClick(slot)}
                              title={`Click to choose ${slot}`}
                            >
                              <span className="slot-chip-time">{timeLabel}</span>
                              <span className="slot-chip-badge">45m</span>
                              <span className="slot-chip-action">
                                {isSelected ? '✓ Selected' : 'Choose ➔'}
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Interactive Selected Slot Dock */}
            {selectedSlot && (
              <div className="selected-slot-dock">
                <div className="dock-info">
                  <span className="dock-tag">Selected Slot:</span>
                  <strong className="dock-time">
                    {formatFullDate(selectedSlot)} • {formatTimeOnly(selectedSlot)}
                  </strong>
                  <span className="dock-doctor">with {doctor.name}</span>
                </div>
                <div className="dock-actions">
                  <button
                    id="instant-reschedule-btn"
                    className="btn-instant-reschedule"
                    onClick={() => handleInstantBook(selectedSlot)}
                    title="Send reschedule command to 12-step pipeline"
                  >
                    ⚡ Instant Reschedule ➔
                  </button>
                  <button
                    className="btn-dock-cancel"
                    onClick={() => {
                      playClick();
                      setSelectedSlot(null);
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        </>
      )}

      {/* TAB 3: Real-Time Audit Trail */}
      {activeTab === 'audit' && (
        <div className="audit-trail-section">
          <div className="section-subtitle" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>Electronic Health Record Mutation Ledger</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <button
                className={`day-filter-chip ${auditFilter === 'ALL' ? 'active' : ''}`}
                style={{ padding: '3px 10px', fontSize: '0.7rem' }}
                onClick={() => setAuditFilter('ALL')}
              >
                All Clinic Events ({auditEntries.length})
              </button>
              <button
                className={`day-filter-chip ${auditFilter === 'PATIENT' ? 'active' : ''}`}
                style={{ padding: '3px 10px', fontSize: '0.7rem' }}
                onClick={() => setAuditFilter('PATIENT')}
              >
                Only {activePatient.name} ({auditEntries.filter((l) => l.patient_id === activePatientId).length})
              </button>
            </div>
          </div>
          <p className="slots-help-text">
            Cryptographically timestamped audit log of all scheduling actions and checkpoint mutations:
          </p>

          {auditEntries.filter((l) => auditFilter === 'ALL' || l.patient_id === activePatientId).length === 0 ? (
            <div className="no-slots-box">
              No database mutations on file for {auditFilter === 'ALL' ? 'the clinic' : activePatient.name}.
            </div>
          ) : (
            <div className="audit-table-wrapper">
              <table className="audit-table">
                <thead>
                  <tr>
                    <th>Timestamp</th>
                    <th>Action</th>
                    <th>Appointment</th>
                    <th>Patient</th>
                    <th>Old Slot</th>
                    <th>New Confirmed Slot</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {auditEntries
                    .filter((l) => auditFilter === 'ALL' || l.patient_id === activePatientId)
                    .map((log, i) => (
                    <tr key={i} className="audit-row">
                      <td className="mono-cell">
                        {log.timestamp ? log.timestamp.split('T')[1]?.slice(0, 8) : '--:--'}
                      </td>
                      <td>
                        <span className="audit-action-tag">{log.action}</span>
                      </td>
                      <td className="mono-cell highlight">{log.appointment_id}</td>
                      <td>{log.patient_id}</td>
                      <td className="mono-cell text-muted">{log.old_slot ? formatTimeOnly(log.old_slot) : '--'}</td>
                      <td className="mono-cell text-cyan">{log.new_slot ? `${formatFullDate(log.new_slot).split(',')[1]} ${formatTimeOnly(log.new_slot)}` : '--'}</td>
                      <td>
                        <span className="audit-status-tag">✓ {log.status}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
