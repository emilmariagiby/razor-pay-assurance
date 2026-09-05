<div align="center">

# 🛡️ Assurance
### Financial Outcome Verification for Payment Systems

*Detects when money was collected twice. Explains why. Fixes it. Proves it was fixed.*

[![Python](https://img.shields.io/badge/Python-3.13-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green?logo=fastapi)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react)](https://react.dev)
[![Tests](https://img.shields.io/badge/Tests-90%20passed-brightgreen?logo=pytest)](backend/tests)
[![Scenarios](https://img.shields.io/badge/Scenarios-45%20deterministic-orange)](backend/simulator)

</div>

---

## 🧠 The Problem, in Plain English

Imagine a customer tries to pay Rs 25,000. The bank takes too long to respond — the gateway marks it as "timed out". Your system's recovery agent thinks the payment failed and automatically retries it. A second payment goes through successfully.

Then, 4 minutes later, the *original* payment also goes through.

**The customer has now been charged Rs 50,000 for a single order.**

No error was thrown. No alarm fired. Both banks said "success". The books just quietly disagreed.

This is a **late authorization after retry** — and it's extremely hard to catch automatically because every individual step was technically correct.

**Assurance catches it.** Then it explains exactly what happened, recommends a refund, and waits for proof that the customer's money was actually returned before marking the case resolved.

---

## 🔑 The Most Important Idea

> **A payment timeout is NOT a failure. It is uncertainty.**

Most systems treat `timeout = failed`. Assurance treats it as `UNCERTAIN` — because the bank might still authorize that payment later (and often does). This single distinction is what makes late-authorization duplicates detectable.

```mermaid
stateDiagram-v2
    direction LR
    [*] --> CREATED: payment.created
    CREATED --> AUTHORIZED: payment.authorized
    CREATED --> TIMEOUT: payment.timeout
    CREATED --> FAILED: payment.failed
    CREATED --> CANCELLED: payment.cancelled
    AUTHORIZED --> CAPTURED: payment.captured
    TIMEOUT --> UNCERTAIN: (waiting...)
    UNCERTAIN --> AUTHORIZED: late auth arrives ⚡
    UNCERTAIN --> CAPTURED: late capture arrives ⚡
    UNCERTAIN --> FAILED: finally fails
    CAPTURED --> REFUNDED: refund.processed
```

---

## 🎬 How It Works End-to-End

```mermaid
flowchart LR
    A[Payment Events\ngateway / bank / agent] --> B[Reconstruct\nPayment State]
    B --> C{Did the books\nadd up?}
    C -- Yes --> D[✅ Clean\nNo action needed]
    C -- No --> E[🚨 Violation Detected]
    E --> F[Build Causal Graph\nWhy did this happen?]
    F --> G[Recommend Action\ne.g. Refund Rs 25,000]
    G --> H[Human Approves]
    H --> I[Execute via\nRazorpay API]
    I --> J[Wait for Webhook Proof\nrefund.processed]
    J --> K[✅ ASSURED\nCase Closed]
```

---

## 🏗️ Architecture

```mermaid
graph TB
    subgraph Input["📥 Input"]
        W[Razorpay Webhooks]
        S[Simulator Scenarios]
        U[Add Case UI]
    end

    subgraph Core["⚙️ Core Engine"]
        FE[FinancialEvent]
        ES[EventStream]
        PSM[Payment State Machine]
        IE[Invariant Engine\n45 deterministic rules]
        AE[Assurance Engine]
        CG[Causal Graph]
    end

    subgraph Output["📤 Case"]
        AC[AssuranceCase\nViolation + Exposure + Action]
        EX[Explanation]
        RM[Risk Advisory]
    end

    subgraph Resolution["🔧 Resolution"]
        HA[Human Approval]
        RP[Razorpay Refund API]
        WH[Webhook Proof\nrefund.processed]
        AS[ASSURED ✅]
    end

    W --> FE
    S --> FE
    U --> FE
    FE --> ES
    ES --> PSM
    PSM --> IE
    IE --> AE
    AE --> CG
    AE --> AC
    AC --> EX
    AC --> RM
    AC --> HA
    HA --> RP
    RP --> WH
    WH --> AS
```

---

## 🚨 The Flagship Scenario

```mermaid
sequenceDiagram
    participant G as Gateway
    participant B as Bank
    participant A as Agent
    participant AS as Assurance

    G->>B: Authorize pay_A (Rs 25,000)
    Note over B: Taking too long...
    G-->>G: TIMEOUT → pay_A is UNCERTAIN
    G->>A: Notify timeout
    A->>G: Retry — create pay_B
    G->>B: Authorize pay_B
    B-->>G: pay_B Authorized ✓
    G-->>G: pay_B Captured ✓

    Note over B: Original auth finally resolves
    B-->>G: pay_A Authorized (4 min late) ⚡
    G-->>G: pay_A Captured ✓

    G->>AS: All events streamed
    AS->>AS: 2 successful captures for 1 order
    AS-->>G: DUPLICATE_COLLECTION\nExposure: Rs 25,000
```

---

## 📊 What It Detects (45 Scenarios)

```mermaid
mindmap
  root((Assurance))
    Retry
      Duplicate Collection
      Late Authorization
      Multiple Captures
      Uncertain Payment Captured
      Conflicting Agent Action
    Refund
      Refund Exceeds Captured
      Duplicate Refund
      Refund Reversal
      Refund SLA Breach
      Refund Without Capture
    Settlement
      Settlement Variance
      Unexplained Adjustment
      Cross-Cycle Discrepancy
      Missing Settlement
    Dispute
      Missing Evidence
      Contradictory Evidence
      Late Evidence
      Already Refunded Dispute
```

---

## ✅ Case Lifecycle

```mermaid
stateDiagram-v2
    direction LR
    [*] --> OPEN: Violation detected
    OPEN --> RESOLVING: Refund executed (live mode)
    OPEN --> ASSURED: Refund executed (simulation)
    RESOLVING --> ASSURED: refund.processed webhook ✓
    RESOLVING --> OPEN: Refund failed
    OPEN --> FALSE_POSITIVE: Manually dismissed
```

---

## 🧬 Why Deterministic Rules, Not Just ML?

```mermaid
flowchart TD
    A[EventStream] --> B[Rebuild payment state]
    B --> C{Invariant checks}
    C --> D[Only 1 successful capture\nper order?]
    C --> E[Total refunded never\nexceeds captured?]
    C --> F[Settlement matches\ncaptured funds?]
    C --> G[Dispute evidence\nconsistent with payment?]
    D -- No --> H[DUPLICATE_COLLECTION]
    E -- No --> I[REFUND_EXCEEDS_CAPTURED]
    F -- No --> J[SETTLEMENT_VARIANCE]
    G -- No --> K[DISPUTE_EVIDENCE_CONTRADICTION]
```

If these math checks fail, there is a real financial problem — no probability, no threshold, no false positive risk from model drift. ML is used as an **advisory layer only**.

---

## 🧪 ML Validation (IEEE-CIS)

We validated a Random Forest trained on IEEE-CIS fraud data with a **chronological split** (train on older data, test on newer) to simulate real deployment:

| Metric | Random Split | Chronological Split |
|---|---|---|
| **ROC-AUC** | 0.83 | 0.76 |
| **Fraud Recall** | 0.64 | 0.47 |
| **Fraud Precision** | 0.13 | 0.11 |

The random split was giving us an overly optimistic picture. This is why ML is advisory only — the deterministic engine is the source of truth.

---

## 🚀 Getting Started

```bash
# Backend
cd backend
python -m venv .venv && .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload
# → http://localhost:8000

# Frontend
cd frontend
npm install && npm run dev
# → http://localhost:5173

# Tests
cd backend
python -m pytest tests/ -v
# → 90 passed
```

---

## 📁 Project Structure

```
razorpay/
├── backend/
│   ├── app/
│   │   ├── models/event.py          # FinancialEvent, EventType (30+ types)
│   │   ├── state/payment.py         # PaymentStateMachine (TIMEOUT→UNCERTAIN)
│   │   ├── invariants/payment.py    # InvariantEngine, 45 violation checks
│   │   ├── engine.py                # AssuranceEngine (orchestrator)
│   │   ├── graph/causal.py          # Causal graph builder + chain extractor
│   │   ├── cases/assurance.py       # AssuranceCase lifecycle
│   │   ├── learning/memory.py       # OutcomeMemory, historical risk scoring
│   │   ├── ai/explainer.py          # Grounded explanation text
│   │   ├── connectors/              # Razorpay webhook verifier + API client
│   │   ├── db/                      # SQLAlchemy models, SQLite persistence
│   │   └── api/routes.py            # All API endpoints
│   ├── simulator/scenarios.py       # 45 deterministic scenario factories
│   └── tests/                       # 90 tests
├── frontend/
│   └── src/App.jsx                  # React dashboard
└── notebooks/
    └── external_behavior_training.ipynb  # IEEE-CIS ML validation
```

---

## 🌐 API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `GET` | `/scenarios` | All 45 scenarios with ground truth |
| `GET` | `/scenarios/{name}` | Run a named scenario |
| `POST` | `/assurance/cases` | Submit a custom event stream |
| `GET` | `/assurance/cases` | List all cases |
| `GET` | `/assurance/cases/{id}/timeline` | Chronological event evidence |
| `GET` | `/assurance/cases/{id}/graph` | Causal DAG for visualization |
| `GET` | `/assurance/cases/{id}/explanation` | Grounded explanation |
| `GET` | `/assurance/cases/{id}/audit` | Financial audit trail |
| `GET` | `/assurance/cases/{id}/risk` | Historical risk advisory |
| `POST` | `/assurance/cases/{id}/actions/refund` | Execute refund |
| `POST` | `/webhooks/razorpay` | Incoming provider webhook |

---

## ➕ Custom Event Streams

Paste any payment event sequence into the **+ ADD CASE** drawer:

```json
{
  "name": "My custom scenario",
  "amount_inr": 25000,
  "events": [
    {"event_type": "payment.created",    "payment_id": "pay_A", "amount": 2500000, "timestamp": "2026-09-02T10:00:00Z", "source": "gateway"},
    {"event_type": "payment.timeout",    "payment_id": "pay_A",                    "timestamp": "2026-09-02T10:00:05Z", "source": "gateway"},
    {"event_type": "agent.retry_initiated", "payment_id": "pay_A",                 "timestamp": "2026-09-02T10:00:30Z", "source": "agent"},
    {"event_type": "payment.created",    "payment_id": "pay_B", "amount": 2500000, "timestamp": "2026-09-02T10:00:34Z", "source": "agent"},
    {"event_type": "payment.authorized", "payment_id": "pay_B", "amount": 2500000, "timestamp": "2026-09-02T10:00:36Z", "source": "bank"},
    {"event_type": "payment.captured",   "payment_id": "pay_B", "amount": 2500000, "timestamp": "2026-09-02T10:00:37Z", "source": "gateway"},
    {"event_type": "payment.authorized", "payment_id": "pay_A", "amount": 2500000, "timestamp": "2026-09-02T10:04:12Z", "source": "bank"},
    {"event_type": "payment.captured",   "payment_id": "pay_A", "amount": 2500000, "timestamp": "2026-09-02T10:04:13Z", "source": "gateway"}
  ]
}
```

---

<div align="center">

**Assurance** — Because "the API returned 200" is not proof the customer got their money back.

*Razorpay Hackathon Project*

</div>
