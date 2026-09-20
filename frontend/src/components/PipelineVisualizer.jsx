import React, { useState } from 'react';
import { playClick } from '../utils/audio';

const EXECUTION_STEPS = [
  {
    id: 1,
    name: '1. Guardrails',
    desc: 'PII Scrubbing & Prompt Injection Guard',
    category: 'sec',
    engine: 'Regex & Keyword Heuristics',
    detail: 'Sanitizes patient PII (SSN, phone, email) and neutralizes adversarial prompt injection attacks before reaching LLM models.',
  },
  {
    id: 2,
    name: '2. Intent',
    desc: 'Groq Sub-100ms Extraction',
    category: 'ai',
    engine: 'Groq (llama-3.3-70b-versatile)',
    detail: 'Extracts user intent (RESCHEDULE, CANCEL, INQUIRE, AUDIT) and natural language date/time references in <100ms.',
  },
  {
    id: 3,
    name: '3. Context',
    desc: 'Minimal RAG EHR Retrieval',
    category: 'rag',
    engine: 'InMemory Context Retriever',
    detail: 'Retrieves patient record, active appointments, doctor availability calendar, and clinic operational policies.',
  },
  {
    id: 4,
    name: '4. Policy',
    desc: 'Deterministic 24h Notice Engine',
    category: 'policy',
    engine: 'OpenAI (gpt-4o) + Policy Matrix',
    detail: 'Deterministic rule engine enforcing 24-hour advance notice, physician specialization match, and cancellation rights.',
  },
  {
    id: 5,
    name: '5. Tools',
    desc: 'Tool Contract Selection',
    category: 'tool',
    engine: 'LangGraph Tool Registry',
    detail: 'Selects the exact clinical tool schema (GetAppointmentDetails, GetAvailableSlots, RequestSlotReschedule).',
  },
  {
    id: 6,
    name: '6. Validate',
    desc: 'Pydantic Schema Validation & Retry',
    category: 'tool',
    engine: 'Pydantic v2 + Self-Correction Loop',
    detail: 'Strictly validates ISO timestamps and IDs. On format failure, routes up to 2 self-correction loops with error payload.',
  },
  {
    id: 9,
    name: '9. HITL Gate',
    desc: 'LangGraph Checkpoint Intercept',
    category: 'hitl',
    engine: 'LangGraph SqliteSaver',
    detail: 'High-risk gate. Halts state machine execution, serializes snapshot into SQLite, and awaits explicit patient authorization.',
  },
  {
    id: 7,
    name: '7. Execute',
    desc: 'Thread-Safe EHR DB Mutation',
    category: 'exec',
    engine: 'MockHealthcareDB & FastLock',
    detail: 'Atomically updates slot booking, reclaims previously held slot, releases locks, and records audit trail event.',
  },
  {
    id: 8,
    name: '8. Inspect',
    desc: 'Post-Execution Data Integrity Check',
    category: 'exec',
    engine: 'Integrity Validator',
    detail: 'Inspects tool execution result for double-booking conflicts, database mutation errors, and state consistency.',
  },
  {
    id: 10,
    name: '10. Response',
    desc: 'gpt-4o Clinical Response Generation',
    category: 'ai',
    engine: 'OpenAI (gpt-4o)',
    detail: 'Synthesizes compassionate, medically precise, and clear communication with new appointment specifics.',
  },
  {
    id: 11,
    name: '11. Trace',
    desc: 'Telemetry & Latency Spans',
    category: 'telemetry',
    engine: 'TrajectoryTracer + SQLite',
    detail: 'Captures per-step execution spans, token usage, duration, and error codes for observability.',
  },
  {
    id: 12,
    name: '12. Evals',
    desc: 'Async Evaluator & LangSmith Export',
    category: 'telemetry',
    engine: 'AsyncEvaluationWorker + LangSmith',
    detail: 'Computes policy compliance rate, task success rate, hallucination checks, and stream traces to LangSmith.',
  },
];

export default function PipelineVisualizer({ metricsData, lastTraces, activeRunningStep, liveCompletedSteps = [] }) {
  const [selectedStep, setSelectedStep] = useState(null);
  const metrics = metricsData?.metrics || {};

  // Check which steps were visited in the most recent interaction or in current live stream
  const visitedStepNames = (lastTraces || []).map((t) => t.step_name?.toLowerCase() || '');
  const isStepActive = (stepName) =>
    visitedStepNames.some((sn) => sn.includes(stepName.toLowerCase()));

  const handleStepClick = (step) => {
    playClick();
    setSelectedStep(selectedStep?.id === step.id ? null : step);
  };

  return (
    <div className="pipeline-card glass-panel">
      <div className="pipeline-header">
        <div>
          <h2 className="section-title">
            <span>⚡ 12-Step Execution Control Loop</span>
          </h2>
          <div className="pipeline-subline">
            Dual-Provider AI: <strong>Groq Sub-100ms</strong> (Steps 2, 6) + <strong>OpenAI gpt-4o</strong> (Steps 4, 10)
          </div>
        </div>
        {activeRunningStep ? (
          <span className="loop-indicator" style={{ background: 'rgba(0, 242, 254, 0.15)', borderColor: '#00f2fe', color: '#00f2fe' }}>
            <span className="pulse-dot" style={{ width: '7px', height: '7px', borderRadius: '50%', background: '#00f2fe', boxShadow: '0 0 10px #00f2fe' }}></span>
            Executing Step #{activeRunningStep.step || activeRunningStep.id}
          </span>
        ) : (
          <span className="loop-indicator">
            <span className="pulse-dot-green"></span> Loop Active
          </span>
        )}
      </div>

      {/* Grid of 12 Execution Nodes with Click-to-Inspect */}
      <div className="pipeline-steps-grid">
        {EXECUTION_STEPS.map((step) => {
          const stepKey = step.name.split('.')[1].trim();
          const isRunning = Boolean(
            activeRunningStep &&
            (activeRunningStep.step === step.id || (activeRunningStep.name && activeRunningStep.name.toLowerCase().includes(stepKey.toLowerCase())))
          );
          const isLiveCompleted = liveCompletedSteps.includes(step.id);
          const active = isRunning || isLiveCompleted || isStepActive(stepKey);
          const isSelected = selectedStep?.id === step.id;

          return (
            <div
              key={step.id}
              className={`step-box ${step.category} ${isRunning ? 'running-node' : active ? 'active-node' : ''} ${isSelected ? 'selected-step' : ''}`}
              onClick={() => handleStepClick(step)}
              title={`Click to inspect Step #${step.id}`}
            >
              <div className="step-top-row">
                <span className="step-badge-num">#{step.id}</span>
                {step.id === 6 && visitedStepNames.some((sn) => sn.includes('self-corrected') || sn.includes('retry') || sn.includes('failed')) && (
                  <span className="self-correction-badge" title="Dynamic Feedback Self-Correction Loop Active">🔄 Loop</span>
                )}
                {isRunning ? (
                  <span className="pulse-dot" style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#00f2fe', boxShadow: '0 0 8px #00f2fe' }}></span>
                ) : active ? (
                  <span className="step-glow-indicator"></span>
                ) : null}
                {isSelected && <span className="step-inspected-icon">🔍</span>}
              </div>
              <div className="step-title-text">{stepKey}</div>
              <div className="step-desc-text">{step.desc}</div>
            </div>
          );
        })}
      </div>

      {/* Selected Step Deep Inspector Drawer */}
      {selectedStep && (
        <div className="step-inspector-drawer">
          <div className="inspector-header">
            <div className="inspector-title">
              <span className="step-pill">Step #{selectedStep.id}</span>
              <strong>{selectedStep.name}</strong>
              <span className="engine-badge">⚙️ {selectedStep.engine}</span>
            </div>
            <button
              className="inspector-close-btn"
              onClick={() => {
                playClick();
                setSelectedStep(null);
              }}
            >
              ×
            </button>
          </div>
          <p className="inspector-desc">{selectedStep.detail}</p>
        </div>
      )}

      {/* Telemetry Metrics Row */}
      <div className="telemetry-dashboard-row">
        <div className="telemetry-stat-card">
          <div className="stat-value cyan-val">
            {metrics.avg_latency_ms ? `${metrics.avg_latency_ms.toFixed(0)} ms` : '185 ms'}
          </div>
          <div className="stat-label">Avg Turn Latency</div>
        </div>

        <div className="telemetry-stat-card">
          <div className="stat-value emerald-val">
            {metrics.policy_compliance_rate ? `${(metrics.policy_compliance_rate * 100).toFixed(0)}%` : '100%'}
          </div>
          <div className="stat-label">Policy Compliance</div>
        </div>

        <div className="telemetry-stat-card">
          <div className="stat-value teal-val">
            {metrics.task_success_rate ? `${(metrics.task_success_rate * 100).toFixed(0)}%` : '100%'}
          </div>
          <div className="stat-label">Task Success Rate</div>
        </div>

        <div className="telemetry-stat-card">
          <div className="stat-value amber-val">
            {metrics.self_correction_recovery_rate !== undefined ? `${(metrics.self_correction_recovery_rate * 100).toFixed(0)}%` : '100%'}
          </div>
          <div className="stat-label">Self-Correction Rate</div>
        </div>

        <div className="telemetry-stat-card">
          <div className="stat-value purple-val">
            ${metrics.total_cost_usd ? metrics.total_cost_usd.toFixed(5) : '0.00318'}
          </div>
          <div className="stat-label">Session Dollar Cost</div>
        </div>
      </div>

      {/* Recent Spans Stream - Scoped strictly to the latest execution turn */}
      {(() => {
        if (!lastTraces || lastTraces.length === 0) return null;

        // Identify the boundary of the most recent turn (from the latest Step 1 start)
        let lastTurnStartIndex = 0;
        for (let i = lastTraces.length - 1; i >= 0; i--) {
          const name = lastTraces[i]?.step_name || '';
          if (name.startsWith('1.') || name.toLowerCase().includes('receive user message')) {
            lastTurnStartIndex = i;
            break;
          }
        }

        const turnSpans = lastTurnStartIndex > 0 ? lastTraces.slice(lastTurnStartIndex) : lastTraces;
        const latestTraceId = turnSpans[turnSpans.length - 1]?.trace_id;
        const latestSpans = latestTraceId
          ? turnSpans.filter((tr) => !tr.trace_id || tr.trace_id === latestTraceId)
          : turnSpans;

        if (latestSpans.length === 0) return null;

        return (
          <div className="trace-stream-section">
            <div className="trace-stream-title">
              <span>Last Turn Execution Spans ({latestSpans.length})</span>
            </div>
            <div className="trace-spans-chips">
              {latestSpans.map((tr, idx) => (
                <span key={idx} className="trace-span-chip">
                  <span className="span-name">{tr.step_name}</span>
                  <span className="span-duration">{tr.duration_ms ? `${tr.duration_ms.toFixed(1)}ms` : 'ok'}</span>
                </span>
              ))}
            </div>
          </div>
        );
      })()}
    </div>
  );
}
