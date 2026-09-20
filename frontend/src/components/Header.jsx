import React from 'react';
import { playClick } from '../utils/audio';

export default function Header({
  threadId,
  onResetDB,
  isResetting,
  activePatientId,
  onSelectPatient,
  soundEnabled,
  onToggleSound,
}) {
  return (
    <header className="header-bar">
      {/* Brand Identity */}
      <div className="brand-section">
        <div className="brand-logo-icon">
          <span className="logo-pulse"></span>
          🩺
        </div>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h1 className="brand-title">NovaHealth Clinical Portal</h1>
            <span className="brand-badge">LangGraph 12-Step</span>
          </div>
          <p className="brand-sub">Healthcare Scheduling & Deterministic Policy Intelligence</p>
        </div>
      </div>

      {/* Patient Switcher & Multi-Tenant Isolation */}
      <div className="patient-switcher-group">
        <span className="switcher-label">Active Patient:</span>
        <div className="patient-pills-container">
          <button
            id="btn-switch-p101"
            className={`patient-pill ${activePatientId === 'P101' ? 'active' : ''}`}
            onClick={() => {
              playClick();
              onSelectPatient('P101');
            }}
            title="Switch to Alice Walker (Cardiology • Dr. Sarah Chen • Reschedule Eligible >24h)"
          >
            <span className="pill-avatar">AW</span>
            <div className="pill-info">
              <span className="pill-name">Alice Walker</span>
              <span className="pill-mrn">P101 • MRN90210</span>
            </div>
            {activePatientId === 'P101' && <span className="pill-active-dot"></span>}
          </button>

          <button
            id="btn-switch-p102"
            className={`patient-pill ${activePatientId === 'P102' ? 'active' : ''}`}
            onClick={() => {
              playClick();
              onSelectPatient('P102');
            }}
            title="Switch to Bob Miller (Dermatology • Dr. Marcus Vance • <24h Policy Block Demo)"
          >
            <span className="pill-avatar p102">BM</span>
            <div className="pill-info">
              <span className="pill-name">Bob Miller</span>
              <span className="pill-mrn">P102 • MRN48201</span>
            </div>
            {activePatientId === 'P102' && <span className="pill-active-dot"></span>}
          </button>
        </div>
      </div>

      {/* Status & Control Actions */}
      <div className="header-status-group">
        {/* Audio feedback toggle */}
        <button
          id="toggle-sound-btn"
          className={`btn-sound-toggle ${soundEnabled ? 'enabled' : 'muted'}`}
          onClick={() => {
            playClick();
            onToggleSound();
          }}
          title={soundEnabled ? 'Sound feedback enabled (Click to mute)' : 'Sound muted (Click to enable)'}
        >
          <span>{soundEnabled ? '🔊 Sound On' : '🔇 Muted'}</span>
        </button>

        <div className="status-chip" title="LangGraph SQLite state persistence on port 8001">
          <span className="pulse-dot"></span>
          <span>Checkpointer: <strong>SQLite</strong></span>
        </div>

        <button
          id="reset-db-btn"
          className="btn-reset-db"
          onClick={() => {
            playClick();
            onResetDB();
          }}
          disabled={isResetting}
          title="Reset clinic EHR database to initial state"
        >
          {isResetting ? (
            <>
              <span className="spinner-inline"></span> Resetting...
            </>
          ) : (
            '↺ Reset Clinic Data'
          )}
        </button>
      </div>
    </header>
  );
}
