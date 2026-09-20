import React, { useState, useEffect, useCallback } from 'react';
import Header from './components/Header';
import ChatPanel from './components/ChatPanel';
import EHRBoard from './components/EHRBoard';
import PipelineVisualizer from './components/PipelineVisualizer';
import HITLModal from './components/HITLModal';
import Toast from './components/Toast';
import { getSoundEnabled, setSoundEnabled as saveSoundSetting, playSuccess, playClick } from './utils/audio';

const PATIENT_CONFIGS = {
  P101: {
    id: 'P101',
    name: 'Alice Walker',
    mrn: 'MRN90210',
    doctorId: 'DOC1',
    doctorName: 'Dr. Sarah Chen, MD (Cardiology)',
    initialWelcome: {
      role: 'assistant',
      content:
        'Hello **Alice Walker**! I am your NovaHealth Clinical Scheduling Assistant.\n\nI can help you:\n- **Check available openings** with Dr. Sarah Chen, MD\n- **Reschedule your appointment APT-201** (scheduled >24h in advance; eligible for portal reschedule)\n- **Answer questions** regarding your cardiac consultation\n\nHow can I assist you today?',
    },
  },
  P102: {
    id: 'P102',
    name: 'Bob Miller',
    mrn: 'MRN48201',
    doctorId: 'DOC2',
    doctorName: 'Dr. Marcus Vance, MD (Dermatology)',
    initialWelcome: {
      role: 'assistant',
      content:
        'Hello **Bob Miller**! I am your NovaHealth Clinical Scheduling Assistant.\n\nI can help you:\n- **Check available openings** with Dr. Marcus Vance, MD\n- **Review your appointment APT-202** (starts in 6 hours; strictly subject to the 24-hour advance policy)\n- **Answer questions** regarding your dermatology care\n\nHow can I assist you today?',
    },
  },
};

const STORAGE_KEYS = {
  ACTIVE_PATIENT: 'nova_active_patient_id',
  THREADS: 'nova_patient_threads',
  MESSAGES: 'nova_patient_messages',
  DRAFTS: 'nova_patient_drafts',
  TRACES: 'nova_patient_traces',
  APPROVAL: 'nova_patient_pending_approval',
};

function loadStoredState(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (raw) {
      return JSON.parse(raw);
    }
  } catch (err) {
    console.warn(`[NovaHealth] Failed parsing localStorage key ${key}:`, err);
  }
  return typeof fallback === 'function' ? fallback() : fallback;
}

// SSE Streaming reader helper
async function consumeSSEStream(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    let currentEvent = null;
    let currentData = [];

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) {
        if (currentEvent && currentData.length > 0) {
          try {
            const parsed = JSON.parse(currentData.join('\n'));
            onEvent(currentEvent, parsed);
          } catch (e) {
            console.warn('Failed parsing SSE payload:', e);
          }
        }
        currentEvent = null;
        currentData = [];
        continue;
      }

      if (trimmed.startsWith('event:')) {
        currentEvent = trimmed.slice(6).trim();
      } else if (trimmed.startsWith('data:')) {
        currentData.push(trimmed.slice(5).trim());
      }
    }
  }

  // Flush remaining buffer if any
  if (buffer.trim()) {
    const lines = buffer.split('\n');
    let currentEvent = null;
    let currentData = [];
    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith('event:')) {
        currentEvent = trimmed.slice(6).trim();
      } else if (trimmed.startsWith('data:')) {
        currentData.push(trimmed.slice(5).trim());
      }
    }
    if (currentEvent && currentData.length > 0) {
      try {
        const parsed = JSON.parse(currentData.join('\n'));
        onEvent(currentEvent, parsed);
      } catch (e) {
        console.warn('Failed parsing residual SSE payload:', e);
      }
    }
  }
}

export default function App() {
  const [activePatientId, setActivePatientId] = useState(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEYS.ACTIVE_PATIENT);
      return stored && PATIENT_CONFIGS[stored] ? stored : 'P101';
    } catch {
      return 'P101';
    }
  });

  const [activeTab, setActiveTab] = useState('records'); // 'records', 'pipeline', 'audit'
  const [isLoading, setIsLoading] = useState(false);
  const [isSubmittingApproval, setIsSubmittingApproval] = useState(false);
  const [isResetting, setIsResetting] = useState(false);
  const [ehrData, setEhrData] = useState(null);
  const [metricsData, setMetricsData] = useState(null);
  const [soundEnabled, setSoundState] = useState(() => getSoundEnabled());
  const [toasts, setToasts] = useState([]);

  // Live SSE Streaming State
  const [activeRunningStep, setActiveRunningStep] = useState(null);
  const [liveCompletedSteps, setLiveCompletedSteps] = useState([]);
  const [streamingMessage, setStreamingMessage] = useState('');

  // STRICT MULTI-TENANT ISOLATION: Per-Patient independent state trees with LocalStorage Persistence!
  const [patientThreads, setPatientThreads] = useState(() => {
    return loadStoredState(STORAGE_KEYS.THREADS, () => ({
      P101: `thread-p101-${Math.random().toString(36).substring(2, 8)}`,
      P102: `thread-p102-${Math.random().toString(36).substring(2, 8)}`,
    }));
  });

  const [patientMessages, setPatientMessages] = useState(() => {
    return loadStoredState(STORAGE_KEYS.MESSAGES, () => ({
      P101: [PATIENT_CONFIGS.P101.initialWelcome],
      P102: [PATIENT_CONFIGS.P102.initialWelcome],
    }));
  });

  const [patientDrafts, setPatientDrafts] = useState(() => {
    return loadStoredState(STORAGE_KEYS.DRAFTS, {
      P101: '',
      P102: '',
    });
  });

  const [patientTraces, setPatientTraces] = useState(() => {
    return loadStoredState(STORAGE_KEYS.TRACES, {
      P101: [],
      P102: [],
    });
  });

  const [patientPendingApproval, setPatientPendingApproval] = useState(() => {
    return loadStoredState(STORAGE_KEYS.APPROVAL, {
      P101: null,
      P102: null,
    });
  });

  // Automatically persist state updates to localStorage across browser refreshes
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEYS.ACTIVE_PATIENT, activePatientId);
    } catch (e) {}
  }, [activePatientId]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEYS.THREADS, JSON.stringify(patientThreads));
    } catch (e) {}
  }, [patientThreads]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEYS.MESSAGES, JSON.stringify(patientMessages));
    } catch (e) {}
  }, [patientMessages]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEYS.DRAFTS, JSON.stringify(patientDrafts));
    } catch (e) {}
  }, [patientDrafts]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEYS.TRACES, JSON.stringify(patientTraces));
    } catch (e) {}
  }, [patientTraces]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEYS.APPROVAL, JSON.stringify(patientPendingApproval));
    } catch (e) {}
  }, [patientPendingApproval]);

  // Active patient scoped variables
  const currentMessages = patientMessages[activePatientId] || [];
  const currentInputText = patientDrafts[activePatientId] || '';
  const currentThreadId = patientThreads[activePatientId];
  const currentLastTraces = patientTraces[activePatientId] || [];
  const currentPendingApproval = patientPendingApproval[activePatientId] || null;

  const setInputText = (text) => {
    setPatientDrafts((prev) => ({
      ...prev,
      [activePatientId]: text,
    }));
  };

  const addToast = useCallback((message, type = 'info', title = '') => {
    const id = `${Date.now()}-${Math.random().toString(36).substring(2, 6)}`;
    setToasts((prev) => [...prev, { id, message, type, title }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4500);
  }, []);

  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const handleToggleSound = () => {
    const next = !soundEnabled;
    setSoundState(next);
    saveSoundSetting(next);
    addToast(next ? 'Sound feedback enabled' : 'Sound muted', 'info');
  };

  // Fetch live EHR database state
  const fetchEHR = useCallback(async () => {
    try {
      const res = await fetch('/api/ehr');
      if (res.ok) {
        const data = await res.json();
        setEhrData(data);
      }
    } catch (err) {
      console.error('Failed to fetch EHR state:', err);
    }
  }, []);

  // Fetch telemetry and eval metrics
  const fetchMetrics = useCallback(async () => {
    try {
      const res = await fetch('/api/metrics');
      if (res.ok) {
        const data = await res.json();
        setMetricsData(data);
      }
    } catch (err) {
      console.error('Failed to fetch metrics:', err);
    }
  }, []);

  // Initial load
  useEffect(() => {
    fetchEHR();
    fetchMetrics();
  }, [fetchEHR, fetchMetrics]);

  // Handle switching active patient (Strict Isolation: does NOT pollute either patient's chat history!)
  const handleSelectPatient = (patientId) => {
    if (patientId === activePatientId) return;
    setActivePatientId(patientId);
    const targetConfig = PATIENT_CONFIGS[patientId] || PATIENT_CONFIGS.P101;

    addToast(
      `Switched to ${targetConfig.name} (${patientId}). Private health record and isolated chat session loaded.`,
      'info',
      'Session Switched'
    );
  };

  // Interactive slot click: pre-fills chat and prompts user
  const handleSelectSlot = (slotTimestamp) => {
    setInputText(`Please reschedule my appointment to ${slotTimestamp}`);
    addToast(`Selected slot ${slotTimestamp}. Click Send or Instant Reschedule to book.`, 'info', 'Slot Selected');
  };

  // 1-Click Instant Reschedule from Calendar
  const handleInstantReschedule = (slotTimestamp) => {
    handleSendMessage(`Please reschedule my appointment to ${slotTimestamp}`);
  };

  // Start new conversation thread for the active patient ONLY
  const handleClearThread = () => {
    const newThread = `thread-${activePatientId.toLowerCase()}-${Math.random().toString(36).substring(2, 8)}`;
    
    setPatientThreads((prev) => ({
      ...prev,
      [activePatientId]: newThread,
    }));

    setPatientMessages((prev) => ({
      ...prev,
      [activePatientId]: [PATIENT_CONFIGS[activePatientId].initialWelcome],
    }));

    setPatientTraces((prev) => ({
      ...prev,
      [activePatientId]: [],
    }));

    setPatientPendingApproval((prev) => ({
      ...prev,
      [activePatientId]: null,
    }));

    addToast(`Started new consultation thread for ${PATIENT_CONFIGS[activePatientId].name}`, 'info', 'New Thread');
  };

  // Send user message through 12-step graph with real-time SSE streaming
  const handleSendMessage = async (text) => {
    setIsLoading(true);
    setStreamingMessage('');
    setActiveRunningStep({ step: 1, name: '1. Guardrails', title: '1. Guardrails', desc: 'PII Scrubbing & Prompt Injection Guard' });
    setLiveCompletedSteps([]);

    const userMsg = { role: 'user', content: text };

    // Update ONLY active patient's messages
    setPatientMessages((prev) => ({
      ...prev,
      [activePatientId]: [...(prev[activePatientId] || []), userMsg],
    }));

    // Clear draft for this patient
    setPatientDrafts((prev) => ({
      ...prev,
      [activePatientId]: '',
    }));

    const doctorId = activePatientId === 'P101' ? 'DOC1' : 'DOC2';
    const targetThread = currentThreadId;
    let accumulatedText = '';
    let streamCompleted = false;

    try {
      const res = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          patient_id: activePatientId,
          doctor_id: doctorId,
          thread_id: targetThread,
        }),
      });

      if (!res.ok) {
        throw new Error(`API error: ${res.statusText}`);
      }

      await consumeSSEStream(res, (eventType, data) => {
        if (eventType === 'node_start') {
          setActiveRunningStep(data);
        } else if (eventType === 'node_complete') {
          setLiveCompletedSteps((prev) => Array.from(new Set([...prev, data.step])));
        } else if (eventType === 'token') {
          accumulatedText += data.token;
          setStreamingMessage(accumulatedText);
        } else if (eventType === 'hitl_interrupt') {
          setPatientPendingApproval((prev) => ({
            ...prev,
            [activePatientId]: {
              tool: data.tool,
              args: data.args,
              policyReason: data.policy_reason,
              threadId: data.thread_id,
            },
          }));
          addToast('Reschedule requires your confirmation. Please review the authorization dialog.', 'warning', 'Action Required');
        } else if (eventType === 'done') {
          streamCompleted = true;
          // Save traces for active patient
          setPatientTraces((prev) => ({
            ...prev,
            [activePatientId]: data.traces || [],
          }));

          if (!data.requires_approval) {
            playSuccess();
            setPatientMessages((prev) => ({
              ...prev,
              [activePatientId]: [
                ...(prev[activePatientId] || []),
                {
                  role: 'assistant',
                  content: data.final_response,
                  selected_tool: data.selected_tool,
                  policy_code: data.policy_decision?.policy_code,
                  security_flag: data.security_flag,
                },
              ],
            }));
          }
        } else if (eventType === 'error') {
          throw new Error(data.error || 'Streaming error');
        }
      });

      // Refresh database and telemetry
      await fetchEHR();
      await fetchMetrics();
    } catch (err) {
      console.error('Streaming chat error:', err);
      if (!streamCompleted) {
        setPatientMessages((prev) => ({
          ...prev,
          [activePatientId]: [
            ...(prev[activePatientId] || []),
            {
              role: 'assistant',
              content: `Error connecting to healthcare backend: ${err.message}`,
            },
          ],
        }));
        addToast(`Error: ${err.message}`, 'error', 'Network Error');
      }
    } finally {
      setIsLoading(false);
      setActiveRunningStep(null);
      setStreamingMessage('');
    }
  };

  // Resolve Human-in-the-Loop Confirmation with streaming resumption
  const handleResolveApproval = async (approved) => {
    if (!currentPendingApproval) return;
    setIsSubmittingApproval(true);
    setIsLoading(true);
    setStreamingMessage('');
    setActiveRunningStep({ step: 9, name: '9. HITL Gate', title: '9. HITL Gate', desc: 'LangGraph Checkpoint Authorization' });
    setLiveCompletedSteps([]);

    const threadId = currentPendingApproval.threadId;
    let accumulatedText = '';
    let approvalStreamCompleted = false;

    try {
      const res = await fetch('/api/approval/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          thread_id: threadId,
          approved: approved,
        }),
      });

      if (!res.ok) {
        throw new Error(`Approval API error: ${res.statusText}`);
      }

      await consumeSSEStream(res, (eventType, data) => {
        if (eventType === 'node_start') {
          setActiveRunningStep(data);
        } else if (eventType === 'node_complete') {
          setLiveCompletedSteps((prev) => Array.from(new Set([...prev, data.step])));
        } else if (eventType === 'token') {
          accumulatedText += data.token;
          setStreamingMessage(accumulatedText);
        } else if (eventType === 'done') {
          approvalStreamCompleted = true;
          setPatientTraces((prev) => ({
            ...prev,
            [activePatientId]: data.traces || [],
          }));

          // Close modal for active patient
          setPatientPendingApproval((prev) => ({
            ...prev,
            [activePatientId]: null,
          }));

          // Append assistant resolution message to active patient's feed
          setPatientMessages((prev) => ({
            ...prev,
            [activePatientId]: [
              ...(prev[activePatientId] || []),
              {
                role: 'assistant',
                content: data.final_response,
                selected_tool: data.selected_tool,
                policy_code: data.policy_decision?.policy_code,
              },
            ],
          }));

          if (approved) {
            playSuccess();
            addToast('Appointment successfully rescheduled! Health record updated.', 'success', 'Confirmed');
          } else {
            addToast('Reschedule request canceled by patient.', 'info', 'Canceled');
          }
        } else if (eventType === 'error') {
          throw new Error(data.error || 'Approval resume error');
        }
      });

      // Refresh EHR state to reflect database mutation!
      await fetchEHR();
      await fetchMetrics();
    } catch (err) {
      console.error('Approval resume error:', err);
      // Dismiss orphan modal if checkpoint has completed or is not paused
      setPatientPendingApproval((prev) => ({
        ...prev,
        [activePatientId]: null,
      }));
      addToast(`Execution resolved: ${err.message}`, 'info', 'Notice');
    } finally {
      setIsSubmittingApproval(false);
      setIsLoading(false);
      setActiveRunningStep(null);
      setStreamingMessage('');
    }
  };

  // On mount or thread change: verify if the current checkpoint thread in SQLite is paused at HITL
  useEffect(() => {
    if (!currentThreadId) return;
    let isMounted = true;
    const syncThreadState = async () => {
      try {
        const res = await fetch(`/api/chat/thread/${currentThreadId}`);
        if (res.ok && isMounted) {
          const info = await res.json();
          if (info.exists && info.requires_approval) {
            const valArgs = info.validated_args || {};
            setPatientPendingApproval((prev) => ({
              ...prev,
              [activePatientId]: {
                tool: info.selected_tool || 'RequestSlotReschedule',
                args: {
                  appointment_id: valArgs.appointment_id || 'APT-201',
                  patient_id: valArgs.patient_id || activePatientId,
                  new_slot_time: valArgs.new_slot_time,
                  reason: valArgs.reason || 'Patient digital portal request',
                },
                newSlotTime: valArgs.new_slot_time,
                appointmentId: valArgs.appointment_id || 'APT-201',
                patientId: valArgs.patient_id || activePatientId,
                policyReason: info.policy_decision?.reason,
                threadId: currentThreadId,
              },
            }));
          } else if (info.exists && !info.requires_approval) {
            // Thread is not waiting for approval; clear any stale approval state
            setPatientPendingApproval((prev) => ({
              ...prev,
              [activePatientId]: null,
            }));
          }
        }
      } catch (e) {
        // Non-blocking checkpoint sync check
      }
    };
    syncThreadState();
    return () => {
      isMounted = false;
    };
  }, [currentThreadId, activePatientId, ehrData?.appointments]);

  // Reset EHR mock records & reset both patient sessions
  const handleResetDB = async () => {
    setIsResetting(true);
    try {
      const res = await fetch('/api/reset', { method: 'POST' });
      if (res.ok) {
        const freshThreads = {
          P101: `thread-p101-${Math.random().toString(36).substring(2, 8)}`,
          P102: `thread-p102-${Math.random().toString(36).substring(2, 8)}`,
        };
        const freshMessages = {
          P101: [PATIENT_CONFIGS.P101.initialWelcome],
          P102: [PATIENT_CONFIGS.P102.initialWelcome],
        };
        const freshDrafts = { P101: '', P102: '' };
        const freshTraces = { P101: [], P102: [] };
        const freshApprovals = { P101: null, P102: null };

        setPatientThreads(freshThreads);
        setPatientMessages(freshMessages);
        setPatientDrafts(freshDrafts);
        setPatientTraces(freshTraces);
        setPatientPendingApproval(freshApprovals);

        try {
          localStorage.setItem(STORAGE_KEYS.THREADS, JSON.stringify(freshThreads));
          localStorage.setItem(STORAGE_KEYS.MESSAGES, JSON.stringify(freshMessages));
          localStorage.setItem(STORAGE_KEYS.DRAFTS, JSON.stringify(freshDrafts));
          localStorage.setItem(STORAGE_KEYS.TRACES, JSON.stringify(freshTraces));
          localStorage.setItem(STORAGE_KEYS.APPROVAL, JSON.stringify(freshApprovals));
        } catch (e) {}

        await fetchEHR();
        await fetchMetrics();
        addToast('Database, checkpoints, and chat sessions reset to initial state.', 'success', 'Clinic Reset');
      }
    } catch (err) {
      console.error('Reset failed:', err);
      addToast('Failed to reset database', 'error');
    } finally {
      setIsResetting(false);
    }
  };

  const currentPatient = ehrData?.patients?.[activePatientId] || {
    patient_id: activePatientId,
    name: PATIENT_CONFIGS[activePatientId]?.name || 'Patient',
    mrn: PATIENT_CONFIGS[activePatientId]?.mrn || 'MRN00000',
  };

  return (
    <div className="app-layout">
      {/* Top Header */}
      <Header
        threadId={currentThreadId}
        onResetDB={handleResetDB}
        isResetting={isResetting}
        activePatientId={activePatientId}
        onSelectPatient={handleSelectPatient}
        soundEnabled={soundEnabled}
        onToggleSound={handleToggleSound}
      />

      {/* Main Two-Column Workspace */}
      <main className="main-workspace">
        {/* Left Side: Medical AI Chat Workspace (Strictly Isolated to Active Patient) */}
        <ChatPanel
          messages={currentMessages}
          onSendMessage={handleSendMessage}
          isLoading={isLoading}
          currentPatient={currentPatient}
          inputText={currentInputText}
          setInputText={setInputText}
          onSlotSelect={handleSelectSlot}
          onClearThread={handleClearThread}
          streamingMessage={streamingMessage}
          activeRunningStep={activeRunningStep}
        />

        {/* Right Side: Tabbed Electronic Health Record & Pipeline Visualizer */}
        <div className="right-column-container">
          <EHRBoard
            ehrData={ehrData}
            activePatientId={activePatientId}
            onSelectSlot={handleSelectSlot}
            onInstantReschedule={handleInstantReschedule}
            activeTab={activeTab}
            setActiveTab={setActiveTab}
          />

          {/* Show Pipeline Visualizer if pipeline tab is active */}
          {activeTab === 'pipeline' && (
            <PipelineVisualizer
              metricsData={metricsData}
              lastTraces={currentLastTraces}
              activeRunningStep={activeRunningStep}
              liveCompletedSteps={liveCompletedSteps}
            />
          )}
        </div>
      </main>

      {/* Human-in-the-Loop Modal (Strictly Scoped to Active Patient) */}
      <HITLModal
        pendingApproval={currentPendingApproval}
        onResolveApproval={handleResolveApproval}
        isSubmitting={isSubmittingApproval}
      />

      {/* Floating Toast Notification Stack */}
      <Toast toasts={toasts} onDismiss={removeToast} />
    </div>
  );
}
