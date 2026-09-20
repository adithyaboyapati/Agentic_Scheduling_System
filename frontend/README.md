# NovaHealth Clinical Portal — React Frontend

A responsive web application for the NovaHealth LangGraph Healthcare Agent System. Built using **React 19**, **Vite**, and **Vanilla CSS** with a clinical cyber-clean dark mode aesthetic.

---

## Key Features & UI Modules

### 1. Patient Profile Switcher & Multi-Tenant Isolation
- Interactive header pills toggling between **Alice Walker (`P101`)** and **Bob Miller (`P102`)**.
- Strictly isolates clinical records: Alice only sees `APT-201` with Dr. Sarah Chen; Bob only sees `APT-202` with Dr. Marcus Vance.

### 2. Multi-View Tab Navigation
- **📅 Appointment & Open Slots**:
  - **Hero Scheduled Appointment Card**: Dynamic countdown notice (*"In 6 days"*, *"⚠️ In 6 hours - Under 24h notice"*), status indicator (`● CONFIRMED`), physician location, and an expandable **📋 Visit Prep Notes** drawer.
  - **Day Filter Bar**: Filter doctor openings by day (`All Days`, `Tue Sep 22`, `Wed Sep 23`, `Thu Sep 24`, `Fri Sep 25`).
  - **Floating Reschedule Dock**: Selecting an open slot reveals a docked action bar with **"⚡ Instant Reschedule ➔"** (1-click reschedule) and **"💬 Customize in Chat"**.
- **⚡ 12-Step Loop & Telemetry**:
  - Interactive step grid (#1 to #12) with active execution glow and real-time SSE streaming updates.
  - Dynamic **`🔄 Loop` badge** on Step 6 indicating active Pydantic validation self-correction retries.
  - Click any node to open an in-depth **Step Inspector Drawer** explaining engine, responsibilities, and contracts.
  - Real-time performance meters: Average turn latency, policy compliance rate, **self-correction recovery rate**, task success rate, and session token cost.
  - Live execution span chips for the latest turn with token counts and latencies.
- **📜 EHR Audit Trail**:
  - Real-time cryptographic ledger displaying all clinic mutations (timestamp, appointment ID, old slot ➔ new slot, status).

### 3. Medical AI Chat Interface
- **Quick Action Chips**: One-click prompt pills to check open slots, test 24h policy blocks, verify self-correction retry loops, or test prompt injection guards.
- **Same-Slot Notice Awareness**: Automatically recognizes reiterations for the currently booked appointment time and informs user without unnecessary conflict warnings.
- **Clickable Slot Badges**: Datetime references in assistant messages (`🕒 2026-09-24 14:00:00 ➔`) are clickable buttons that pre-fill or trigger rescheduling.
- **Message Controls**: Copy-to-clipboard button with visual feedback, and a "💬 New Thread" button.
- **Dynamic Streaming Indicator**: Displays real-time 12-step execution node progress via SSE.

### 4. Human-in-the-Loop (HITL) Authorization Dialog
- Pops open automatically when LangGraph pauses at the Step 9 gate (`interrupt_before=["human_approval_node"]`).
- Visual transition card: `Target: APT-201 ➔ Authorized New Slot: Sep 24, 2026 • 2:00 PM`.
- Clinical Safety Checklist: Patient MRN verification, 24-hour notice validation, and physician availability verification.
- Authorize and Reject buttons that resume the paused SQLite checkpoint via `/api/approval`.

### 5. Web Audio API Feedback & Toasts
- Synthetic modern audio feedback for clicks, confirmation chimes, and HITL alerts with header mute toggle (`🔊 Sound On` / `🔇 Muted`).
- Non-intrusive floating toast notifications for patient switching, slot selection, and status updates.

---

## Technology Stack

- **Framework**: React 19 + Vite 8
- **Styling**: Vanilla CSS (TailwindCSS avoided per design guidelines)
- **Typography**: Google Fonts (`Outfit` for headings, `Inter` for UI body, `JetBrains Mono` for telemetry and IDs)
- **Audio**: Native HTML5 Web Audio API (zero external sound file dependencies)

---

## Development & Build

### Running Locally
Ensure the backend server is running on port `8001` (`python3 agent_system/server.py`), then start the Vite dev server:

```bash
npm install
npm run dev
```

The application runs on `http://localhost:5173`. Requests to `/api/*` are automatically proxied to `http://localhost:8001` via `vite.config.js`.

### Production Build

```bash
npm run build
```

Build artifacts will be emitted to `dist/`.
