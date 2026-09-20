# NovaHealth AI Clinical Portal & LangGraph 12-Step Agent System

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-orange.svg)](https://github.com/langchain-ai/langgraph)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![React 19](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev/)
[![Vite 8](https://img.shields.io/badge/Vite-8-646cff.svg)](https://vitejs.dev/)
[![Tests Passing](https://img.shields.io/badge/tests-50%20passed-brightgreen.svg)]()

> A production-grade, multi-tenant Agentic AI System implementing a strict **12-Step Execution Control Loop** compiled as a LangGraph `StateGraph`, paired with an interactive clinical portal frontend. Built for automated healthcare appointment rescheduling subject to doctor availability, same-slot detection, and deterministic 24-hour advance cancellation policies.

---

## Architecture Overview

The system executes user interactions through a deterministic, auditable 12-step control loop:

```
[1. Receive Message] ➔ [2. Classify Intent] ➔ [3. Retrieve Context (RAG)]
         │
         ▼
[4. Decide Policy] ➔ [5. Select Tools] ➔ [6. Validate Inputs] ──(Pydantic Error)──┐
         │                                      │                                 │ (Self-Correction
         │                                      │                                 │  Retry Loop ≤2)
         ▼                                      ▼                                 ▼
   [Blocked <24h]                        [Valid Schema] ──────────────────────────┘
         │                                      │
         │                        ┌─────────────┴─────────────┐
         │                        │ Read-Only                 │ High-Risk Write
         │                        ▼                           ▼
         │               [7. Execute Tool]          [9. HITL Gate: Checkpoint Pause]
         │                        │                           │ (Awaiting Patient Authorization)
         │                        ▼                           ▼
         │               [8. Inspect Result]         [Resume Checkpoint via SQLite]
         │                        │                           │
         │                        └─────────────┬─────────────┘
         │                                      │
         ▼                                      ▼
[10. Generate Response (gpt-4o)] ➔ [11. Log Trace Spans] ➔ [12. Async Evaluation & LangSmith]
```

### 12-Step Execution Control Loop Specification

| Step # | Node Name | Component | Functionality |
|:---|:---|:---|:---|
| **1** | `receive_message_node` | `SecurityGuardrails` | Ingests input, resets turn state, scrubs PII (SSN, phone, email, MRN), and detects prompt injection. |
| **2** | `classify_intent_node` | `ModelRouter` (Groq) | Sub-100ms structured intent extraction (`RESCHEDULE`, `CANCEL`, `INQUIRE`, `AUDIT`) via `llama-3.3-70b-versatile`. |
| **3** | `retrieve_context_node` | `ContextRetriever` | Scoped EHR retrieval (active patient record, current appointment, doctor availability) without whole-database dumping. |
| **4** | `check_policy_node` | `PolicyEngine` (OpenAI) | Enforces the strict **24-hour advance notice cancellation rule**, intercepts **redundant same-slot requests (`POLICY_SAME_SLOT`)**, and validates clinician authorization. |
| **5** | `select_tools_node` | Tool Selector & Repair | Resolves tool contracts (`GetAppointmentDetails`, `GetAvailableSlots`, `RequestSlotReschedule`). Operates the **Dynamic Feedback Loop Repair Engine** to self-correct invalid inputs from Step 6. |
| **6** | `validate_tool_args_node` | Pydantic Schema | Validates ISO timestamps, IDs, and date filters with granular error diagnostics. Emits structured diagnostics on failure, triggering Step 5 repair loop (up to 2 retries). |
| **7** | `execute_tool_node` | `BaseHealthcareTool` | Atomic, thread-safe database mutations with execution timeouts and lock safety. |
| **8** | `inspect_results_node` | Integrity Checker | Verifies mutation success, double-booking prevention, and state consistency. |
| **9** | `human_approval_node` | `SqliteSaver` Checkpoint | **Human-in-the-Loop (HITL) Gate**. Pauses graph execution for high-risk write operations, serializes state to SQLite, and awaits explicit user authorization. |
| **10** | `generate_response_node` | `ModelRouter` (OpenAI) | Generates empathetic, structured, and clinically precise communication using `gpt-4o` (or deterministic synthesis on policy notices). |
| **11** | `log_trace_node` | `TrajectoryTracer` | Records granular spans: provider, model, tokens, time-to-first-token, duration, and cost in USD. |
| **12** | `send_eval_data_node` | `AsyncEvaluationWorker` | Asynchronously computes policy compliance, task success, self-correction recovery rate, and exports traces to LangSmith. |

---

## Key System Features

### 1. Dual-Provider AI Architecture & Circuit Breaker
- **Fast Extraction Layer**: Groq (`llama-3.3-70b-versatile` or `llama-3.1-8b-instant`) handles low-latency structured extraction (Steps 2 and 6) in sub-100ms.
- **Clinical Reasoning Layer**: OpenAI (`gpt-4o`) handles nuanced policy reasoning (Step 4) and empathetic patient response generation (Step 10).
- **Circuit Breaker**: Monitored retry handler with states (`CLOSED`, `OPEN`, `HALF-OPEN`). Automatically fails over to `gpt-4o-mini` if Groq encounters rate limits (HTTP 429) or timeouts.

### 2. Dynamic Feedback Self-Correction Loop (Pydantic Validation)
- When Step 6 encounters a Pydantic schema validation error (e.g. malformed timestamp formats, missing seconds, or un-prefixed IDs), a conditional edge captures structured field-level diagnostics (`field`, `input`, `msg`, `type`).
- Routes `Step 6 ➔ Step 5` with the failed arguments and validation feedback.
- `ModelRouter.repair_tool_arguments` inspects the exact Pydantic failure message and repairs the payload (normalizes ISO strings, standardizes appointment and physician IDs, reconciles natural language slots with `available_slots`).
- Bounded to a maximum of **2 retries** (`MAX_RETRIES = 2`) before falling back gracefully to a user-facing clarification message without crashing.
- Live telemetry tracks `self_correction_recovery_rate` and renders a `🔄 Loop` badge in the UI.

### 3. Strict Deterministic Healthcare Policy Engine
- **24-Hour Advance Cancellation Policy**: Appointments scheduled within 24 hours (e.g., Bob Miller's `APT-202` starting in 6 hours) cannot be modified or canceled via the portal. The engine blocks the write tool before Step 7 and directs the patient to call the front desk.
- **Same-Slot Reschedule Interception (`POLICY_SAME_SLOT`)**: If a patient requests rescheduling to a date/time they are *already booked for*, Step 4 detects the match, bypasses tools and HITL confirmation modals, and immediately clarifies that their appointment is already confirmed for that slot.
- **Multi-Tenant Isolation**: Health records are strictly scoped by `patient_id`. Cross-patient access attempts are blocked with zero leakage of appointment timing or clinical notes.
- **Doctor Availability & Conflict Resolution**: If a requested slot is unavailable or outside operating hours, the system politely notifies the patient and presents alternative openings for that physician.

### 4. Human-in-the-Loop (HITL) Checkpoint Intercept Gate
- Configured using LangGraph `interrupt_before=["human_approval_node"]` with persistent SQLite checkpoint storage (`server_checkpoints.db`).
- Pauses the execution thread immediately before committing database mutations.
- The web application displays an authorization dialog detailing the before/after transition, policy validation checklist, and reason.
- When approved, `compiled_graph.update_state()` resumes execution from the exact checkpoint without re-running earlier nodes.

### 5. Interactive Clinical Web Application (Vite + React)
- **Clinical Dark Theme**: Built with Vanilla CSS, glassmorphism (`backdrop-filter: blur(16px)`), and Google Fonts (`Outfit`, `Inter`, `JetBrains Mono`).
- **Patient Profile Switcher**: Instantly switch between **Alice Walker (`P101`)** (Cardiology, reschedule eligible) and **Bob Miller (`P102`)** (Dermatology, `<24h` policy violation demo).
- **Hero Appointment Card**: Relative notice indicators (*"In 6 days"*, *"⚠️ In 6 hours"*), status indicators, physician location, and expandable **Visit Prep Notes**.
- **Interactive Calendar & Slot Browser**: Day filter bar (`All Days`, `Tue Sep 22`, `Wed Sep 23`, `Thu Sep 24`, `Fri Sep 25`) with a **Floating Reschedule Dock** supporting 1-click booking (`⚡ Instant Reschedule ➔`).
- **In-Chat Clickable Slot Badges**: Dates and times mentioned in chat messages are rendered as interactive clickable pills (`🕒 2026-09-24 14:00:00 ➔`).
- **Tabbed Dashboard**: Toggle between **Appointment & Open Slots**, **12-Step Loop & Telemetry** (with interactive step inspector and `🔄 Loop` badge), and real-time **EHR Audit Trail Ledger**.
- **Real-Time SSE Streaming**: Live step-by-step progress emitted over Server-Sent Events (`/api/chat/stream`, `/api/approval/stream`).
- **Web Audio Synthesizer**: Subtle UI audio feedback for button taps, confirmation chimes, and HITL alerts (with header mute toggle).
- **Floating Toast Stack**: Non-intrusive notification banners for all critical operations.

---

## Repository Structure

```
├── README.md                      # Root project documentation (this file)
├── .env.example                   # Environment configuration template
├── server_checkpoints.db          # Persistent SQLite state checkpoints for LangGraph
├── agent_system/                  # Python LangGraph backend package
│   ├── README.md                  # Detailed backend documentation
│   ├── server.py                  # FastAPI REST & SSE streaming server (port 8001)
│   ├── main.py                    # Standalone CLI demo runner
│   ├── walkthrough.md             # In-depth architectural & verification report
│   ├── implementation_plan.md     # Implementation specifications
│   ├── src/
│   │   ├── orchestrator/          # LangGraph StateGraph definitions
│   │   │   ├── graph.py           # StateGraph compilation & interrupt configuration
│   │   │   ├── state.py           # AppointmentAgentState schema (with self-correction fields)
│   │   │   ├── nodes.py           # 12-step execution nodes (with self-correction & same-slot handling)
│   │   │   └── edges.py           # Conditional routing & bounded self-correction retry edges
│   │   ├── models/                # Dual LLM router, repair engine & circuit breaker
│   │   │   ├── router.py          # Groq + OpenAI routing, repair engine, date normalization
│   │   │   ├── circuit_breaker.py # Circuit breaker state machine (Closed, Open, Half-Open)
│   │   │   ├── response_generator.py # Clinical response synthesis & policy messaging
│   │   │   └── schemas.py         # Pydantic schemas, validation models, evaluation metrics
│   │   ├── policies/              # Deterministic clinical rules
│   │   │   ├── engine.py          # 24-hour notice, same-slot detection & slot validation
│   │   │   ├── cancellation_policy.py # 24h boundary calculation
│   │   │   └── authorization.py   # Multi-tenant ID verification
│   │   ├── security/              # Security and guardrail engine
│   │   │   ├── guardrails.py      # Unified PII & injection processor
│   │   │   ├── pii_sanitizer.py   # Regex/NER PII token replacement
│   │   │   └── injection_guard.py # Prompt injection detection
│   │   ├── tools/                 # Tool implementations & mock database
│   │   │   ├── base.py            # BaseHealthcareTool contract with structured diagnostics
│   │   │   ├── appointment_tools.py # GetDetails, GetSlots, RequestReschedule
│   │   │   └── mock_db.py         # Thread-safe in-memory singleton clinic DB
│   │   ├── evals/                 # Telemetry & evaluation framework
│   │   │   ├── tracer.py          # Step execution span tracer & cost tracking
│   │   │   └── worker.py          # Async evaluation metrics engine (recovery rate, compliance)
│   │   └── storage/               # Memory retrievers
│   │       └── memory.py          # Context retriever implementation
│   └── tests/                     # Comprehensive test suite (50 tests passing)
│       ├── test_edge_cases.py     # 12 production edge cases (security, failover, persistence, race conditions)
│       ├── test_guardrails.py     # PII & injection tests
│       ├── test_policies.py       # 24h rule, authorization, and same-slot tests
│       ├── test_router_circuit.py # Dual-provider & circuit breaker tests
│       ├── test_self_correction.py# Pydantic dynamic feedback loop tests
│       ├── test_state_graph.py    # End-to-end 12-step flow tests
│       ├── test_streaming.py      # SSE streaming & thread persistence tests
│       └── test_tools.py          # Tool schema & execution tests
└── frontend/                      # React + Vite clinical portal
    ├── README.md                  # Detailed frontend documentation
    ├── package.json
    ├── vite.config.js             # Dev server & port 8001 API proxy configuration
    ├── index.html
    └── src/
        ├── App.jsx                # Main workspace shell & state management
        ├── index.css              # Clinical luxury design system & glassmorphism
        ├── utils/
        │   └── audio.js           # Web Audio API sound synthesizer
        └── components/
            ├── Header.jsx         # Patient profile switcher, sound toggle, reset
            ├── ChatPanel.jsx      # Chat feed, quick actions, clickable in-message slots
            ├── EHRBoard.jsx       # Hero appointment card, day filters, slot dock, audit trail
            ├── PipelineVisualizer.jsx # 12-step execution visualizer & step inspector
            ├── HITLModal.jsx      # Checkpoint authorization dialog with transition card
            └── Toast.jsx          # Floating notification stack
```

---

## Getting Started

### Prerequisites
- **Python**: 3.10 or newer
- **Node.js**: 18.0 or newer (with `npm`)
- API Keys:
  - `OPENAI_API_KEY` (Required for Policy Reasoning & Response Generation)
  - `GROQ_API_KEY` (Optional for Sub-100ms Extraction; system automatically falls back to OpenAI if omitted)
  - `LANGCHAIN_API_KEY` (Optional for LangSmith trace export)

### 1. Environment Setup

Copy `.env.example` to `.env` in the project root and add your API keys:

```bash
cp .env.example .env
```

```ini
OPENAI_API_KEY=sk-...
GROQ_API_KEY=gsk_...
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=novahealth-healthcare-agent
```

### 2. Backend Installation & Startup

Install backend dependencies:

```bash
pip install langgraph langchain-openai langchain-groq pydantic fastapi uvicorn python-dotenv pytest
```

Start the FastAPI backend server on port `8001`:

```bash
python3 agent_system/server.py
```

The API will be accessible at `http://localhost:8001`. Interactive OpenAPI documentation is available at `http://localhost:8001/docs`.

### 3. Frontend Installation & Startup

In a separate terminal window:

```bash
cd frontend
npm install
npm run dev
```

Open your browser at **`http://localhost:5173`**.

---

## Running Automated Tests

Run the complete test suite across all 12 steps, production edge cases, self-correction dynamic feedback loops, and streaming handlers:

```bash
PYTHONPATH=agent_system python3 -m pytest agent_system/tests -v
```

### Test Suite Summary (50/50 Passing)

```text
agent_system/tests/test_edge_cases.py::test_edge_case_1_1_mixed_pii_and_indirect_injection PASSED
agent_system/tests/test_edge_cases.py::test_edge_case_1_2_reversible_pii_roundtrip_unmasking PASSED
agent_system/tests/test_edge_cases.py::test_edge_case_2_1_groq_api_429_circuit_breaker_failover_mid_trajectory PASSED
agent_system/tests/test_edge_cases.py::test_edge_case_2_2_circuit_breaker_half_open_probe_recovery PASSED
agent_system/tests/test_edge_cases.py::test_edge_case_3_1_ambiguous_fuzzy_input_self_correction_repair PASSED
agent_system/tests/test_edge_cases.py::test_edge_case_3_2_irreparable_garbage_input_exhaustion_fallback PASSED
agent_system/tests/test_edge_cases.py::test_edge_case_4_1_23h_59m_strict_policy_boundary PASSED
agent_system/tests/test_edge_cases.py::test_edge_case_4_2_unauthorized_cross_patient_rescheduling PASSED
agent_system/tests/test_edge_cases.py::test_edge_case_4_3_prompt_patient_override_rejected PASSED
agent_system/tests/test_edge_cases.py::test_edge_case_4_4_reschedule_to_currently_booked_slot PASSED
agent_system/tests/test_edge_cases.py::test_edge_case_5_1_process_crash_restart_during_hitl_interruption PASSED
agent_system/tests/test_edge_cases.py::test_edge_case_5_2_explicit_human_rejection_at_hitl_gate PASSED
agent_system/tests/test_edge_cases.py::test_edge_case_6_1_concurrent_slot_reservation_race_condition PASSED
agent_system/tests/test_guardrails.py::test_pii_sanitization_ssn_email_phone PASSED
agent_system/tests/test_guardrails.py::test_injection_guard_flags_malicious_inputs PASSED
agent_system/tests/test_guardrails.py::test_injection_guard_passes_benign_healthcare_requests PASSED
agent_system/tests/test_guardrails.py::test_security_guardrails_unified_processing PASSED
agent_system/tests/test_policies.py::test_24_hour_cancellation_policy_allowed PASSED
agent_system/tests/test_policies.py::test_24_hour_cancellation_policy_denied PASSED
agent_system/tests/test_policies.py::test_authorization_validator PASSED
agent_system/tests/test_policies.py::test_policy_engine_reschedule_scenarios PASSED
agent_system/tests/test_router_circuit.py::test_circuit_breaker_transitions_and_fallback PASSED
agent_system/tests/test_router_circuit.py::test_model_router_groq_to_openai_failover PASSED
agent_system/tests/test_router_circuit.py::test_model_router_cost_calculation PASSED
agent_system/tests/test_self_correction.py::test_self_correction_recovers_unprefixed_and_spaced_timestamp PASSED
agent_system/tests/test_self_correction.py::test_self_correction_recovers_missing_seconds_timestamp PASSED
agent_system/tests/test_self_correction.py::test_self_correction_recovers_date_filter PASSED
agent_system/tests/test_self_correction.py::test_self_correction_bounded_exhaustion PASSED
agent_system/tests/test_self_correction.py::test_eval_metrics_self_correction_recovery_rate PASSED
agent_system/tests/test_state_graph.py::test_flow_read_only_query_executes_without_interrupt PASSED
agent_system/tests/test_state_graph.py::test_flow_write_reschedule_hitl_pause_and_approval_resume PASSED
agent_system/tests/test_state_graph.py::test_flow_write_reschedule_hitl_rejection PASSED
agent_system/tests/test_state_graph.py::test_flow_policy_violation_blocks_reschedule PASSED
agent_system/tests/test_state_graph.py::test_flow_prompt_injection_blocked_at_security_gate PASSED
agent_system/tests/test_async_eval_worker_metrics_computation PASSED
agent_system/tests/test_state_graph.py::test_self_correction_retry_loop_success PASSED
agent_system/tests/test_state_graph.py::test_self_correction_retry_exhaustion_fallback PASSED
agent_system/tests/test_state_graph.py::test_reschedule_inquiry_without_slot_prompts_user_for_datetime PASSED
agent_system/tests/test_state_graph.py::test_reschedule_with_unavailable_slot_notifies_conflict_and_offers_alternatives PASSED
agent_system/tests/test_multiturn_no_rejection_state_pollution PASSED
agent_system/tests/test_streaming.py::test_streaming_chat_endpoint_yields_sse_events PASSED
agent_system/tests/test_streaming.py::test_streaming_approval_endpoint_yields_sse_events PASSED
agent_system/tests/test_streaming.py::test_get_thread_history_endpoint PASSED
agent_system/tests/test_streaming.py::test_streaming_error_handling_invalid_payload PASSED
agent_system/tests/test_tools.py::test_get_appointment_details_tool PASSED
agent_system/tests/test_tools.py::test_get_appointment_details_unauthorized PASSED
agent_system/tests/test_tools.py::test_get_available_slots_tool PASSED
agent_system/tests/test_request_slot_reschedule_tool_success PASSED
agent_system/tests/test_request_slot_reschedule_invalid_slot_format PASSED

============================= 50 passed in 88.01s =============================
```

---

## API Reference

### `POST /api/chat`
Invokes the 12-step graph with a user message synchronously.

**Request Body:**
```json
{
  "message": "Please reschedule my appointment to 2026-09-24 14:00:00",
  "patient_id": "P101",
  "doctor_id": "DOC1",
  "thread_id": "optional-thread-id"
}
```

**Response Body (when paused at HITL Gate):**
```json
{
  "thread_id": "thread-a1b2c3d4",
  "requires_approval": true,
  "hitl_status": "WAITING_APPROVAL",
  "final_response": "Action Required: Moving or canceling your existing appointment requires patient confirmation...",
  "selected_tool": "RequestSlotReschedule",
  "validated_args": {
    "patient_id": "P101",
    "appointment_id": "APT-201",
    "new_slot_time": "2026-09-24T14:00:00"
  },
  "traces": [...]
}
```

### `POST /api/chat/stream`
Executes message processing with live Server-Sent Events (SSE) streaming each completed node and progress in real time.

### `POST /api/approval`
Resumes an interrupted graph execution from its SQLite checkpoint synchronously.

**Request Body:**
```json
{
  "thread_id": "thread-a1b2c3d4",
  "approved": true
}
```

### `POST /api/approval/stream`
Streams execution resume events over SSE after patient grants or rejects HITL approval.

### `GET /api/chat/thread/{thread_id}`
Returns the stored turn messages and trace records for a specific conversation thread.

### `GET /api/ehr`
Returns the real-time database state (appointments, doctors, open slots, audit log).

### `GET /api/metrics`
Returns evaluation metrics computed asynchronously (task success rate, policy compliance rate, self-correction recovery rate, average latency, total token cost).

### `POST /api/reset`
Resets the clinic database, traces, and metrics to clean initial state.

---

## License

This project is licensed under the MIT License.
