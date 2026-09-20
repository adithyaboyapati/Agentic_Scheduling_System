# Agent System — LangGraph 12-Step Healthcare Backend

The `agent_system` Python package implements a deterministic, production-grade 12-step execution control loop compiled as a LangGraph `StateGraph` for clinical appointment rescheduling, policy verification, and human-in-the-loop authorization.

---

## Directory Structure

```text
agent_system/
├── server.py               # FastAPI backend REST & SSE streaming server (/api/chat, /api/chat/stream, etc.)
├── main.py                 # CLI demo runner executing transactional scenarios
├── requirements.txt        # Python package dependencies
├── walkthrough.md          # Detailed engineering report, edge cases, and test results
├── implementation_plan.md  # Architectural plan and specifications
├── src/
│   ├── orchestrator/       # LangGraph core workflow definitions
│   │   ├── graph.py        # StateGraph construction & SqliteSaver configuration
│   │   ├── state.py        # AppointmentAgentState schema with self-correction history
│   │   ├── nodes.py        # Implementation of all 12 execution nodes
│   │   └── edges.py        # Conditional routing, same-slot bypass & bounded self-correction retry
│   ├── models/             # Dual LLM provider router, repair engine & circuit breaker
│   │   ├── router.py       # Groq extraction & OpenAI reasoning with schema repair engine
│   │   ├── circuit_breaker.py # Circuit breaker state machine (Closed, Open, Half-Open)
│   │   ├── response_generator.py # Clinical response synthesis & policy messaging
│   │   └── schemas.py      # Pydantic schemas, validation models, evaluation metrics
│   ├── policies/           # Deterministic clinical rules engine
│   │   ├── engine.py       # 24-hour cancellation rule & same-slot reschedule interception
│   │   ├── cancellation_policy.py # 24h boundary calculation
│   │   └── authorization.py# Multi-tenant ID verification
│   ├── security/           # PII and prompt injection guardrails
│   │   ├── guardrails.py   # Unified security processor
│   │   ├── pii_sanitizer.py# PII regex/NER anonymizer
│   │   └── injection_guard.py # Adversarial injection detector
│   ├── tools/              # Clinical tool registry & mock EHR database
│   │   ├── base.py         # BaseHealthcareTool abstract contract with structured diagnostics
│   │   ├── appointment_tools.py # GetDetails, GetSlots, RequestReschedule tools
│   │   └── mock_db.py      # Thread-safe in-memory singleton clinic database
│   ├── evals/              # Observability & evaluation framework
│   │   ├── tracer.py       # Step execution span tracer & dynamic cost tracking
│   │   └── worker.py       # Async worker computing policy compliance & recovery rate
│   └── storage/            # Minimal RAG context retrievers
│       └── memory.py       # In-memory context retriever
└── tests/                  # Pytest test suite (50 passing tests)
    ├── test_edge_cases.py  # 12 production edge cases (security, failover, persistence, race conditions)
    ├── test_guardrails.py  # PII & injection tests
    ├── test_policies.py    # 24h rule, authorization, and same-slot tests
    ├── test_router_circuit.py # Dual-provider & circuit breaker tests
    ├── test_self_correction.py# Pydantic dynamic feedback loop tests
    ├── test_state_graph.py # End-to-end 12-step flow tests
    ├── test_streaming.py   # SSE streaming & thread persistence tests
    └── test_tools.py       # Tool schema & execution tests
```

---

## 12-Step Execution Control Loop Specification

```
Receive Message (1) ➔ Classify Intent (2) ➔ Retrieve Context (3)
       │
       ▼
Decide Scope/Policy (4) ➔ Select Tools (5) ➔ Validate Tool Inputs (6) ──(Schema Error)──┐
       │                                              │                                 │ (Self-Correction
       │                                              │                                 │  Retry Loop ≤2)
       ▼                                              ▼                                 ▼
 [Policy Denied]                               [Valid Schema] ──────────────────────────┘
 (or Same-Slot)                                       │
       │                                ┌─────────────┴─────────────┐
       │                                │ Read-Only                 │ High-Risk Write
       │                                ▼                           ▼
       │                       Execute Tools (7)           HITL Gate Pause (9)
       │                                │                           │ (Patient Approval)
       │                                ▼                           ▼
       │                       Inspect Results (8)          Resume via SQLite Checkpoint
       │                                │                           │
       │                                └─────────────┬─────────────┘
       │                                              │
       ▼                                              ▼
Generate Response (10) ➔ Log Trace Spans (11) ➔ Send Async Eval Data (12)
```

---

## Running the Backend

### 1. Interactive FastAPI REST & Streaming API Server

```bash
python3 agent_system/server.py
```

Runs on port `8001`. Key endpoints:
- `POST /api/chat`: Runs message synchronously through the 12-step graph. If paused at Step 9, returns `requires_approval: true`.
- `POST /api/chat/stream`: Emits real-time Server-Sent Events (SSE) as each graph node executes.
- `POST /api/approval`: Resumes execution synchronously from SQLite checkpoint with user's approval decision.
- `POST /api/approval/stream`: Resumes execution and streams remaining node events over SSE.
- `GET /api/chat/thread/{thread_id}`: Retrieves stored turns and telemetry traces for a conversation thread.
- `GET /api/ehr`: Returns live EHR database state (appointments, doctors, open slots, audit log).
- `GET /api/metrics`: Returns async evaluation metrics (task success rate, policy compliance rate, self-correction recovery rate).
- `POST /api/reset`: Resets clinic database and telemetry to initial state.

### 2. Standalone CLI Demo

```bash
python3 agent_system/main.py --demo
```

Executes transactional scenarios in terminal:
1. Read-only slot availability inquiry.
2. Compliant reschedule (>24h notice) with HITL checkpoint pause and resume.
3. Policy violation (<24h notice) blocked before write execution.
4. Same-slot reschedule request politely acknowledged without redundant mutations.
5. PII scrubbing and prompt injection defense.
6. Pydantic validation failure and self-correction retry loop.

---

## Running Tests

Execute all 50 unit, integration, edge case, and policy tests:

```bash
PYTHONPATH=agent_system python3 -m pytest agent_system/tests -v
```
