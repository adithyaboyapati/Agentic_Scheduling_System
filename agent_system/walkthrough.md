# Technical Walkthrough: Production-Grade LangGraph Healthcare Agent System

We have engineered, verified, and delivered an end-to-end production-grade Agentic AI System in Python using **LangGraph** (`langgraph`), implementing a strict **12-Step Execution Control Loop** coupled with a high-performance **FastAPI** backend and an interactive **React + Vite** clinical portal.

---

## 1. 12-Step Execution Control Loop Architecture

The system compiles a LangGraph `StateGraph` with 12 distinct steps ensuring deterministic execution, strict security guardrails, policy verification, and human-in-the-loop safety:

```
[1. Receive Message] ➔ [2. Classify Intent] ➔ [3. Retrieve Context]
         │
         ▼
[4. Decide Policy] ➔ [5. Select Tools] ➔ [6. Validate Inputs] ──(Schema Error)──┐
         │                                      │                               │ (Self-Correction
         │                                      │                               │  Retry Loop ≤2)
         ▼                                      ▼                               ▼
   [Blocked <24h]                        [Valid Schema] ────────────────────────┘
         │                                      │
         │                        ┌─────────────┴─────────────┐
         │                        │ Read-Only                 │ High-Risk Write
         │                        ▼                           ▼
         │               [7. Execute Tool]          [9. HITL Gate: Checkpoint Pause]
         │                        │                           │ (Awaiting User Decision)
         │                        ▼                           ▼
         │               [8. Inspect Result]         [Resume via SQLite Checkpoint]
         │                        │                           │
         │                        └─────────────┬─────────────┘
         │                                      │
         ▼                                      ▼
[10. Generate Response (gpt-4o)] ➔ [11. Log Trace Spans] ➔ [12. Async Evaluation & LangSmith]
```

---

## 2. Multi-Tenant Session & Conversation Isolation

In a multi-patient clinical portal, conversation histories, checkpoints, and pending approvals must remain strictly isolated per patient.

### Implementation Details:
1. **Isolated State Trees**: `patientMessages`, `patientThreads`, `patientDrafts`, `patientTraces`, and `patientPendingApproval` are maintained as per-patient state dictionaries keyed by `patientId` (`P101` vs `P102`).
2. **Persistent Isolated Checkpoints**: Each patient maintains their own independent LangGraph thread ID (`thread-p101-...` vs `thread-p102-...`), ensuring state checkpoints in `server_checkpoints.db` never collide.
3. **Tailored Initial Welcomes**: Each patient receives a personalized onboarding message referencing their primary physician, department, and active appointment notice status.
4. **Adaptive Quick Actions**: Chat prompt chips adapt to the active patient (e.g. Dr. Chen cardiology prompts for Alice vs. Dr. Vance dermatology prompts for Bob).
5. **Ephemeral State Reset on Profile Switch**: In `EHRBoard`, active slot selections, clinical notes drawers, and day filters reset when switching profiles.
6. **Audit Trail Scoping**: The EHR Audit Ledger allows toggling between viewing all clinic events and filtering strictly to the active patient's mutation events.

### Proof of Complete Conversation Isolation:

#### Alice Walker (`P101`) Isolated Session
![Alice Walker Isolated Chat](/Users/adithyaboyapati/.gemini/antigravity-ide/brain/114aeb8d-4da0-4e01-b0d7-7441aeb64f3f/alice_walker_isolated_chat_1789762714296.png)

#### Bob Miller (`P102`) Isolated Session
![Bob Miller Isolated Chat](/Users/adithyaboyapati/.gemini/antigravity-ide/brain/114aeb8d-4da0-4e01-b0d7-7441aeb64f3f/bob_miller_isolated_chat_1789762733051.png)

---

## 3. Verification & Test Suite

All **50 tests** in `agent_system/tests` pass with 100% success rate:
```bash
PYTHONPATH=agent_system python3 -m pytest agent_system/tests -v
============================= 50 passed in 88.01s ==============================
```
- Frontend builds cleanly in Vite: `✓ built in 136ms`.
- Autonomous browser validation confirmed complete message isolation when toggling between Alice Walker and Bob Miller.

---

## 4. Dynamic Feedback Self-Correction Loop (Step 5 ↔ Step 6)

### Architecture
```
[Step 5: Select Tools] ──(raw_args)──► [Step 6: Validate Tool Inputs]
        ▲                                          │
        │                                    (Pydantic Error)
        │                                          ▼
   (Self-Correction) ◄── [route_after_validation] ◄─ (retry_count < 2)
  repair_tool_arguments             │
                                (retry_count >= 2)
                                    ▼
                         [Step 10: Fallback Response]
```

- **Pydantic Diagnostics**: Captures `field`, `input`, `msg`, and `type` on schema validation exceptions.
- **Repair Engine (`ModelRouter.repair_tool_arguments`)**: Normalizes malformed timestamps (`2026-09-24 14:00:00` or missing seconds ➔ `2026-09-24T14:00:00`), standardizes IDs (`201` ➔ `APT-201`), and maps natural language queries to open openings.
- **Loop Bounded**: Enforces `MAX_RETRIES = 2` before graceful fallback.
- **Telemetry**: Evaluates `self_correction_recovery_rate` and renders dynamic `🔄 Loop` badge on Step 6.

---

## 5. Same-Slot Reschedule Redundant Request Interception (`POLICY_SAME_SLOT`)

### Problem
When a slot is booked, it is committed to EHR records and removed from `available_slots`. If the patient subsequent asks to reschedule to that exact same slot, naive slot lookup would flag it as "unavailable / conflict".

### Solution
1. **Policy Engine (`Step 4: check_policy_node`)**: Evaluates `target_slot` against `apt.get("slot_time")`. If matching, returns `POLICY_SAME_SLOT` (`allowed = False`, `requires_confirmation = False`).
2. **Short-Circuit Bypass (`route_after_policy`)**: Directly routes `Step 4 ➔ Step 10`, eliminating redundant mutations, schema loops, or HITL modals.
3. **Clinical Notice**: Politeness synthesis confirms: *"You are already scheduled for this date and time: [date/time] with [Doctor]. Your appointment ([ID]) is confirmed, so no changes are needed."*

---

## 6. Real-Time Server-Sent Events (SSE) Streaming

- `/api/chat/stream` and `/api/approval/stream` emit granular node events (`node_start`, `node_finish`, `step_progress`, `hitl_waiting`) enabling real-time visual tracking on the frontend 12-step pipeline.
