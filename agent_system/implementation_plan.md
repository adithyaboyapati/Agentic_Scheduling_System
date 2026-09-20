# Implementation Plan & Architectural Spec: NovaHealth LangGraph Healthcare Agent

Completed technical architecture and specifications for the end-to-end 12-step LangGraph healthcare appointment rescheduling and policy enforcement system, paired with the clinical web portal.

---

## 1. System Architecture

```mermaid
flowchart TD
    subgraph Client [React + Vite Clinical Portal - :5173]
        Header[Header & Patient Switcher AW / BM]
        Chat[Chat Panel & In-Message Clickable Slot Badges]
        EHR[EHR Hero Card, Day Filters & Instant Slot Dock]
        Inspector[12-Step Inspector & Live Trace Spans]
        Audit[Real-Time EHR Audit Ledger]
        HITLModal[HITL Authorization Modal & Checklist]
    end

    subgraph Server [FastAPI REST Server - :8001]
        API["REST API (/api/chat, /api/approval, /api/ehr, /api/metrics, /api/reset)"]
        Checkpointer[(SQLite State Checkpointer)]
    end

    subgraph Graph [LangGraph 12-Step StateGraph]
        Step1[1. Receive Message & PII/Injection Guard]
        Step2[2. Classify Intent via Groq Sub-100ms]
        Step3[3. Retrieve Context Minimal EHR]
        Step4[4. Decide Policy 24h Window via OpenAI gpt-4o]
        Step5[5. Select Tools & Resolve Conflicts]
        Step6[6. Validate Inputs & Self-Correction Retry]
        Step7[7. Execute Tool & DB Mutation]
        Step8[8. Inspect Results & Integrity]
        Step9[9. HITL Checkpoint Gate]
        Step10[10. Generate Response via gpt-4o]
        Step11[11. Log Trace Spans & Costs]
        Step12[12. Async Evals & LangSmith]
    end

    Header --> API
    Chat -->|POST /api/chat| API
    EHR --> API
    HITLModal -->|POST /api/approval| API
    API --> Graph
    Graph --> Checkpointer
    Step9 -.->|Interrupt & Pause| Checkpointer
    Checkpointer -.->|Resume State| Step9
```

---

## 2. Completed Components

### Backend (`agent_system/`)
- **Dual Model Router & Circuit Breaker**: Groq (`llama-3.3-70b-versatile`) for Steps 2 & 6; OpenAI (`gpt-4o`) for Steps 4 & 10; automatic failover to `gpt-4o-mini` on Groq 429/timeouts.
- **Dynamic Feedback Self-Correction Loop**: Conditional routing `Step 6 ➔ Step 5` on Pydantic schema validation failures with structured diagnostics (`field`, `input`, `msg`, `type`), bounded to `MAX_RETRIES = 2`.
- **Deterministic 24-Hour Policy Engine**: Blocks reschedule or cancellation requests for appointments occurring within 24 hours (e.g. `APT-202`).
- **Same-Slot Reschedule Interception (`POLICY_SAME_SLOT`)**: Intercepts requests attempting to reschedule to the active appointment's already booked date/time, short-circuiting tools and HITL gates to provide a clear confirmation notice.
- **Flexible Natural Slot Normalizer & Repair Engine**: Parses ISO, 12h/24h timestamps, AM/PM, natural dates (`09-24 17:00:00`, `Sep 24 at 2pm`), and repairs malformed inputs.
- **Conflict Handling**: Politely explains physician unavailability and offers open slots.
- **Persistent HITL Gate**: LangGraph `interrupt_before=["human_approval_node"]` with `SqliteSaver` (`server_checkpoints.db`).
- **Real-Time Streaming**: Server-Sent Events (SSE) endpoints (`/api/chat/stream`, `/api/approval/stream`) streaming step execution and progress.
- **Observability & Telemetry**: Dynamic token tracking, cost computation in USD, `self_correction_recovery_rate`, and LangSmith integration.

### Frontend (`frontend/`)
- **Design System**: Clinical cyber-clean dark mode in Vanilla CSS with glassmorphism and Google Fonts (`Outfit`, `Inter`, `JetBrains Mono`).
- **Multi-Tenant Profile Isolation**: Independent state trees for `patientMessages`, `patientThreads`, `patientDrafts`, `patientTraces`, and `patientPendingApproval` keyed by `patientId` (`P101` vs `P102`). Toggling profiles never leaks messages, and each session runs against its own LangGraph checkpoint thread.
- **Segmented Portal Tabs**: Toggle between **Appointment & Open Slots**, **12-Step Loop & Telemetry** (with interactive step inspector and `🔄 Loop` badge), and **EHR Audit Trail Ledger**.
- **Hero Appointment Card**: Relative notice indicator, clinic room location, and expandable **Visit Prep Notes**.
- **Day Filter Bar & Slot Dock**: Filter by day and use **"⚡ Instant Reschedule ➔"** for 1-click booking without typing.
- **Interactive In-Message Slots**: Assistant slot suggestions render as clickable buttons.
- **Web Audio Feedback & Toasts**: Synthesized audio feedback for clicks, success chimes, and HITL alerts (with mute toggle), plus floating toasts.

---

## 3. Verification & Test Coverage

- **50 Pytest Tests Passing** (`PYTHONPATH=agent_system python3 -m pytest agent_system/tests -v`):
  - 12 Production Edge Cases (`test_edge_cases.py`)
  - 5 Pydantic Self-Correction Loop Tests (`test_self_correction.py`)
  - 4 Streaming & Thread History Tests (`test_streaming.py`)
  - 4 Deterministic Policy Tests (`test_policies.py`)
  - 4 Security & Guardrail Tests (`test_guardrails.py`)
  - 3 Router & Circuit Breaker Tests (`test_router_circuit.py`)
  - 13 End-to-End StateGraph Tests (`test_state_graph.py`)
  - 5 Tool Contract Tests (`test_tools.py`)
- **Production Vite Build**: Clean build in **136ms**.
- **Live Multi-Turn Verification**: Validated same-slot reschedule notice, HITL authorization, self-correction repair loops, and streaming updates.
