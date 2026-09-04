# Assurance Project Walkthrough

A concise explanation guide for presenting the Assurance financial outcome verification project.

## 1. One-Sentence Explanation

Assurance ingests financial events, reconstructs payment state, detects invariant violations, explains their causal chain, recommends a controlled action, and verifies the final outcome through provider webhooks.

The flagship story is a late authorization after an automated retry, which causes duplicate collection. The same architecture also covers refund, settlement, and dispute failures.

## 2. End-to-End Architecture

```text
Razorpay webhook / simulator / custom API events
                    |
                    v
             FinancialEvent
                    |
                    v
              EventStream
                    |
                    v
       Payment and workflow state machines
                    |
                    v
             InvariantEngine
                    |
                    v
             AssuranceEngine
                    |
          +---------+---------+
          |                   |
          v                   v
    Causal graph        AssuranceCase
          |                   |
          +---------+---------+
                    v
          Explanation and risk memory
                    |
                    v
       Human-approved corrective action
                    |
                    v
     Razorpay API or simulation lifecycle
                    |
                    v
           Provider webhook proof
                    |
                    v
          Same stream re-evaluation
                    |
                    v
                 ASSURED
```

## 3. The Flagship Scenario

`simulator/scenarios.py -> late_auth_duplicate()` creates this sequence:

1. Payment A is created for Rs 25,000.
2. The gateway times out. Timeout means `UNCERTAIN`, not failed.
3. The recovery agent starts a retry.
4. Payment B is created by the agent.
5. Payment B is authorized and captured.
6. Payment A is authorized and captured late.
7. The invariant engine detects two successful captures for one order.
8. Assurance reports Rs 25,000 duplicate exposure.
9. A human approves the refund.
10. Simulation mode produces a complete synthetic refund lifecycle and becomes `ASSURED`.
11. Razorpay test mode calls the refund API and remains `RESOLVING`.
12. `refund.processed` arrives, is correlated by refund ID, appended to the original stream, and verifies the same case.

This is the best demo because it shows detection, explanation, action, asynchronous verification, and learning in one closed loop.

## 4. Important Concepts and Symbols

### 4.1 Event Contract

File: `backend/app/models/event.py`

- `EventType`: canonical vocabulary for payment, retry, refund, settlement, dispute, and agent events.
- `EventSource`: identifies gateway, bank, agent, merchant, Razorpay, customer, or Assurance origin.
- `FinancialEvent`: the atomic fact stored by the system. Important fields are `event_id`, `event_type`, `timestamp`, entity IDs, amount, source, causal parent, and metadata.
- `FinancialEvent.normalize_timestamp()`: converts every timestamp to timezone-aware UTC. This prevents naive/aware datetime comparison failures during stream ordering.
- `EventStream`: ordered append-only collection for an order or merchant.
- `EventStream.add()`: appends an event and sorts chronologically.
- `EventStream.by_type()`, `for_payment()`, and `for_refund()`: query helpers used by state machines and invariants.
- `EventStream.payment_ids` and `refund_ids`: distinct entity identifiers derived from events.

Key explanation: the system stores what happened, not only the final state. State is reconstructed from the event history.

### 4.2 Assurance Engine

File: `backend/app/engine.py`

- `AssuranceEngine.__init__()`: wires the payment state machine, invariant engine, causal graph builder, and chain extractor.
- `AssuranceEngine.investigate(stream)`: central orchestration method.
  1. Resolves each payment.
  2. Evaluates all invariants.
  3. Builds one shared causal graph when violations exist.
  4. Builds one `AssuranceCase` per violation.
- `AssuranceEngine._build_case()`: converts a raw invariant violation into a complete case containing workflow, severity, exposure, expected/observed state, evidence, causal chain, confidence, and recommendation.
- `AssuranceEngine._map_violation_type()`: maps invariant-layer types to public case-layer types.
- `AssuranceEngine._find_target_event()`: selects the outcome event from which the causal explanation should be traced.
- `AssuranceEngine._recommend()`: chooses the corrective action and whether human approval is required.
- `AssuranceEngine._determine_workflow()`: groups a violation into retry, refund, settlement, or dispute.
- `AssuranceEngine._compute_confidence()`: gives structural deterministic findings high confidence and uncertain findings lower confidence.

Key explanation: ML or risk scoring may advise, but the deterministic engine remains the authority for whether a financial invariant was violated.

### 4.3 Payment State Reconstruction

File: `backend/app/state/payment.py`

- `PaymentState`: includes `CREATED`, `AUTHORIZED`, `CAPTURED`, `FAILED`, `TIMEOUT`, `UNCERTAIN`, `CANCELLED`, and refund states.
- `SUCCESSFUL_STATES`: identifies states that represent a successful collection, including captured and refunded states.
- `PaymentStateMachine.TRANSITIONS`: explicit allowed transitions.
- `PaymentStateMachine.EVENT_TO_STATE`: maps event types to state changes.
- `PaymentStateMachine.resolve(payment_id, stream)`: walks the payment's events chronologically and returns a `ResolvedPayment`.
- `ResolvedPayment.is_successful`, `.is_uncertain`, and `.is_terminal`: convenient state predicates.

Most important domain decision: `TIMEOUT` is not `FAILED`. It becomes `UNCERTAIN`, because the original payment may still authorize later.

### 4.4 Invariant Detection

File: `backend/app/invariants/payment.py`

- `ViolationType`: raw invariant vocabulary.
- `ViolationSeverity`: `CRITICAL`, `HIGH`, `MEDIUM`, and `LOW`.
- `InvariantViolation`: raw detection result with description, exposure, expected state, observed state, involved IDs, and evidence event IDs.
- `OrderFinancialState`: aggregate captured/refunded/net values and successful/uncertain payment lists.
- `InvariantEngine.evaluate(stream)`: runs payment/refund, settlement, and evidence checks.
- Important checks include:
  - `_check_duplicate_collection()`
  - `_check_refund_limits()`
  - `_check_duplicate_refunds()`
  - `_check_refund_reversals()`
  - `_check_late_authorization()`
  - `_check_settlement_variance()`
  - `_check_evidence_invariants()`

The 20 simulator scenarios validate this broad deterministic coverage. They are not all ML training examples.

### 4.5 Causal Explanation

File: `backend/app/graph/causal.py`

- `CausalGraphBuilder.build(stream)`: creates a directed graph with event nodes and causal edges.
- Explicit edges use `caused_by_event_id`.
- Inferred edges come from domain rules.
- `_infer_retry_causality()`: connects timeout -> retry -> agent-created payment.
- `_infer_payment_lifecycle()`: connects events belonging to the same payment.
- `_infer_late_authorization()`: connects late authorization/capture behavior to the earlier uncertain flow.
- `CausalChainExtractor.extract()`: turns a graph path into readable steps.
- `CausalChain`: stores the summary and ordered causal steps.
- `CausalRelation`: standard labels such as `triggered`, `created`, `resolved`, `preceded`, and `contradicts`.

Key explanation: the graph answers why the event occurred, not merely what event was detected.

### 4.6 Assurance Case Lifecycle

File: `backend/app/cases/assurance.py`

- `ViolationType`: public case types.
- `AssuranceCaseStatus`: `OPEN`, `INVESTIGATING`, `PENDING`, `RESOLVING`, `ASSURED`, and `FALSE_POSITIVE`.
- `RecommendedAction`: actions such as `REFUND_DUPLICATE`, `CONTEST_DISPUTE`, `ACCEPT_DISPUTE`, `ESCALATE`, and `MONITOR`.
- `AssuranceCase`: complete investigation record.
- `approve_recommendation()`: moves an approved case to `RESOLVING`.
- `mark_assured()`: records verified success, resolution time, and outcome details.
- `to_dict()`: API/UI serialization boundary.

Provider lifecycle: API acceptance is not proof that a customer received a refund. Test mode waits for a qualifying webhook before marking the case assured.

### 4.7 API Routes and Persistence Boundary

File: `backend/app/api/routes.py`

In-memory stores:

- `CASE_STORE`: case ID -> `AssuranceCase`.
- `STREAM_STORE`: case ID -> its authoritative `EventStream`.
- `OUTCOME_MEMORY`: historical case outcomes.
- `WEBHOOK_STREAMS`: temporary stream buffer for uncorrelated webhook events.
- `REFUND_TO_CASE`: refund ID -> case ID correlation.
- `PROCESSED_WEBHOOKS`: in-memory webhook idempotency set.

Important endpoints:

- `POST /assurance/analyze`: investigates an `EventStream`, preserving an existing assured case on refresh.
- `GET /assurance/cases`: lists cases with workflow, severity, and status filters.
- `GET /assurance/cases/{case_id}`: returns one case.
- `GET /assurance/cases/{case_id}/timeline`: returns chronological evidence.
- `GET /assurance/cases/{case_id}/graph`: returns graph nodes and causal edges.
- `GET /assurance/cases/{case_id}/audit`: returns the financial audit trail.
- `GET /assurance/cases/{case_id}/explanation`: returns grounded explanation text.
- `GET /assurance/cases/{case_id}/risk`: returns transparent outcome-memory risk.
- `GET /assurance/memory`: exposes stored outcome records.
- `POST /assurance/cases/{case_id}/actions/refund`: executes simulation or provider refund flow.
- `POST /assurance/cases/{case_id}/approve`: records approval without executing the action.
- `POST /webhooks/razorpay`: provider webhook entry point.

`razorpay_webhook()` flow:

1. Read raw body and verify the optional signature.
2. Normalize the provider payload.
3. Ignore duplicate event IDs.
4. Resolve `refund_id -> case_id` when available.
5. Retrieve `STREAM_STORE[case_id]` for correlated refunds.
6. Reject unknown processed refunds without creating a case.
7. Append the event to the existing stream.
8. Re-run the engine on that stream.
9. Update the existing resolving case when the refund is verified.
10. Persist the case and stream references.

`action_refund()` has two deliberate semantics:

- Simulation mode: synthetic request/processed/completed events, then immediate `ASSURED` if exposure is eliminated.
- Razorpay test mode: call provider API, store `REFUND_TO_CASE[refund_id]`, append `REFUND_REQUESTED`, return `RESOLVING`, and wait for webhook proof.

Current persistence limitation: all stores are process memory. A server restart loses cases, streams, correlation mappings, and idempotency history. PostgreSQL is the future persistence boundary.

### 4.8 Razorpay Integration

Files: `backend/app/connectors/razorpay.py` and `razorpay_client.py`

- `EVENT_MAP`: maps Razorpay event names to internal `EventType` values.
- `verify_signature(body, signature, secret)`: HMAC SHA-256 webhook verification.
- `normalize_webhook(payload)`: extracts entity IDs, amounts, provider event type, timestamp, and stable webhook event ID.
- If the provider does not supply an event ID, normalization hashes the canonical payload to make repeated identical deliveries idempotent.
- `RazorpayClient.from_environment()`: enables the provider only when test mode and credentials are configured.
- `RazorpayClient.create_refund()`: server-side refund POST using Basic Auth.
- `RazorpayClient.fetch_payment()`: server-side payment lookup.

Credentials never go to the frontend.

### 4.9 Outcome Memory and ML Direction

File: `backend/app/learning/memory.py`

Current layer: transparent historical risk memory, not a black-box production model.

- `OutcomeFeatures`: current feature vector: workflow, violation type, severity, event count, payment count, capture count, agent action count, timeout presence, and exposure.
- `OutcomeRecord`: features plus case ID, resolved label, action, and timestamp.
- `OutcomeMemory.record()`: captures case features.
- `OutcomeMemory.mark_resolved()`: labels a case as resolved after a verified action.
- `OutcomeMemory.risk_for()`: finds historical cases with matching workflow and violation type, excludes the current case, calculates unresolved rate, and returns a risk score, recommendation, reason, and features.
- `extract_features()`: feature extraction boundary for future workflow-specific features.
- `_risk_reason()`: produces a human-readable explanation for the score.

Recommended ML evolution:

1. Keep `OutcomeMemory` as the transparent label/history store.
2. Extend features with timing, action, amount, lifecycle, settlement, refund, dispute, and agent context.
3. Generate controlled variations of all workflow scenarios.
4. Use deterministic invariant output as the label, not human guesswork.
5. Train/evaluate a simple interpretable risk model.
6. Return model output as advisory risk only; never override deterministic Assurance decisions.

The model should answer: “How risky is this proposed action or current workflow state?” It should not decide whether the books are mathematically inconsistent.

### 4.10 Grounded Explanation

File: `backend/app/ai/explainer.py`

- `GroundedExplanation`: serializable explanation structure.
- `explain_case(case)`: produces bounded explanation text from case evidence and fields.

The explanation layer should remain evidence-bounded: it describes recorded facts and causal links instead of inventing provider behavior.

## 5. Workflow Coverage

## 5A. Master Case Library

This is the recovered case taxonomy from the project discussion. The original 20 simulator scenarios remain the regression and ground-truth foundation. The additional entries below are expansion targets, not replacements for that foundation.

The unifying theme is disagreement or delayed agreement between financial systems: a gateway times out while a bank later authorizes, an agent acts while state is uncertain, a refund is marked processed and later reversed, settlement numbers fail to reconcile, or dispute evidence conflicts with payment history.

### Retry / Payment Cases

1. Late authorization -> duplicate collection (flagship)
2. Retry after timeout
3. Multiple retries -> multiple successful captures
4. Retry after original payment eventually succeeds
5. Retry after payment was already captured
6. Retry after cancellation
7. Retry amount mismatch
8. Uncertain payment gets captured
9. Multiple captures against one order
10. Agent retry causing downstream financial inconsistency

Existing foundation scenarios: `normal_payment`, `retry_success`, `late_auth_duplicate`, `two_legitimate_orders`, and `multiple_retry_anomaly`.

### Refund Cases

1. Refund exceeds captured amount
2. Duplicate refund
3. Refund reversal
4. Refund requested but never completed
5. Refund failure
6. Refund after an already completed refund
7. Refund against an invalid or non-captured payment
8. Refund plus dispute interaction
9. Agent-initiated refund producing an unexpected outcome

Existing foundation scenarios: `refund_clean`, `refund_reversal`, `over_refund`, `duplicate_refund`, and `partial_refund`.

### Settlement Cases

1. Clean or reconciled settlement
2. Settlement variance
3. Unexplained settlement variance
4. Explained variance caused by a known adjustment
5. Settlement missing expected captured funds
6. Settlement amount inconsistent with captured transactions
7. Settlement adjustment without a corresponding financial cause
8. Cross-cycle or previous-cycle adjustment affecting current settlement
9. Capture-to-settlement reconciliation failure

Existing foundation scenarios: `settlement_clean`, `settlement_variance`, `settlement_variance_explained`, `settlement_previous_refund`, and `settlement_chargeback`.

### Dispute Cases

1. Missing dispute evidence
2. Contradictory dispute evidence
3. Dispute created for an already-refunded payment
4. Dispute deadline approaching
5. Automated dispute contested by later evidence
6. Evidence submitted after deadline
7. Dispute outcome inconsistent with financial state
8. Dispute plus refund interaction
9. Dispute plus settlement interaction

Existing foundation scenarios: `dispute_strong_evidence`, `dispute_missing_evidence`, `dispute_contradiction`, `dispute_already_refunded`, and `dispute_deadline_risk`.

### Cross-Workflow Cases

1. Duplicate collection -> refund -> webhook -> `ASSURED` (flagship closed loop)
2. Duplicate collection -> refund reversal -> case reopens
3. Refund completed -> dispute created -> already-refunded conflict
4. Capture -> settlement variance
5. Agent action -> downstream bad financial outcome
6. Refund plus active dispute
7. Dispute plus settlement discrepancy
8. Cross-cycle adjustment combined with an earlier payment anomaly

Cross-workflow cases should reuse the same `EventStream`, state reconstruction, invariant evaluation, causal graph, case lifecycle, action, and verification pipeline. They should not become separate mini-products.

### Case Contract

Every library entry should document:

```text
Scenario
       -> event stream
       -> expected result
       -> actual result
       -> violation type
       -> financial exposure
       -> causal explanation
       -> recommended action
       -> resolution state
       -> verification evidence
```

Target scale: roughly 8-10 cases per workflow family plus cross-workflow cases, giving a meaningful 30+ case library. The exact count should follow distinct financial failure modes, not an arbitrary quota.

### Retry

- Late authorization duplicate.
- Retry after uncertainty.
- Multiple retries.
- Amount mismatch and cancellation-related cases.

Primary symbols: `PaymentStateMachine`, `_check_duplicate_collection()`, `_check_late_authorization()`, retry causal inference.

### Refund

- Over-refund.
- Duplicate refund.
- Refund reversal.
- Refund not completed.
- Refund after other financial activity.

Primary symbols: `_check_refund_limits()`, `_check_duplicate_refunds()`, `_check_refund_reversals()`, refund lifecycle events.

### Settlement

- Settlement variance.
- Explained adjustment.
- Previous refund impact.
- Chargeback/settlement discrepancies.

Primary symbols: `SettlementStateMachine`, `_check_settlement_variance()`, `SETTLEMENT_*` events.

### Dispute

- Missing evidence.
- Contradictory evidence.
- Already refunded dispute.
- Deadline risk.
- Automated dispute action later contested.

Primary symbols: `EvidenceStateMachine`, `_check_evidence_invariants()`, `DISPUTE_*` events.

## 6. Medium-Importance Implementation Details

### Entry Point

File: `backend/main.py`

- Creates the FastAPI application.
- Enables permissive CORS for the local React frontend.
- Includes the Assurance and webhook routers.
- `GET /health`: health check.
- `GET /scenarios`: scenario catalog and expected ground truth.
- `GET /scenarios/{name}`: runs a named simulator scenario.
- `POST /investigate`: accepts raw custom events and runs the engine.

### API Schemas

File: `backend/app/api/schemas.py`

- `AnalyzeRequest`: wraps an `EventStream`.
- `AnalyzeResponse`: list of serialized cases.
- `CaseResponse`: one serialized case.
- `ActionRequest`: optional payment ID and note.
- `ActionResponse`: serialized action result.

### Simulator Helpers

File: `backend/simulator/scenarios.py`

- `_t(seconds)`: creates deterministic scenario time offsets.
- `_make_event(...)`: shared event factory.
- `get_scenario(name)`: validates and returns one scenario.
- `all_scenarios()`: returns the complete scenario matrix.
- `GROUND_TRUTH`: expected violation metadata used by scenario checks.

Scenario groups include retry, refund, settlement, and dispute. `check_all_scenarios.py` runs the matrix and compares actual violations with ground truth.

### Frontend

Files: `frontend/src/App.jsx`, `App.css`, `index.css`, `main.jsx`

`App.jsx` important parts:

- `App()`: loads the hero stream, case, timeline, graph, explanation, audit, risk, and metrics.
- `refreshMetrics()`: refreshes dashboard totals.
- `approveRefund()`: calls the refund action endpoint and refreshes UI data.
- `GraphView()`: renders the causal DAG with React Flow.
- `Overview()`: renders root cause, financial impact, and horizontal evidence trail.
- `RiskNote()`: shows outcome-memory risk without replacing deterministic case data.
- `Timeline()`: renders compact detailed or horizontal event trails.
- `AuditTrail()`: renders evidence-backed activity.
- `Resolution()`: shows approval or verified resolution state.
- `Drawer()`: exposes cases, graph, and audit navigation.
- `fetchJson()`: shared API request/error helper.
- `money()`, `time()`, and `title()`: display formatting helpers.

The dashboard is intentionally a compact single-screen 1080p incident command center. The graph is bounded, the evidence trail is horizontal, and detailed views are separated into tabs.

## 7. Tests and What They Prove

Files: `backend/tests/test_api.py` and `backend/tests/test_late_authorization.py`

Important test groups:

- Payment state tests prove timeout is uncertain and both payments resolve correctly.
- Hero tests prove duplicate collection, exposure, confidence, recommendation, approval requirement, and causal chain.
- Clean scenario tests prove normal flows produce no actionable violations.
- Scenario matrix tests compare all simulator results with `GROUND_TRUTH`.
- API tests cover health, analysis, cases, timeline, graph, audit, metrics, explanations, risk, and memory.
- Refund tests distinguish simulation `ASSURED` from provider `RESOLVING`.
- Webhook tests cover normalization, signature rejection, same-case closure, same-stream attachment, duplicate delivery, and unknown refund isolation.
- Refresh/re-analysis test protects the case ID and assured status after a browser-like reload.

Typical validation commands:

```powershell
Set-Location backend
python -m pytest -q
python check_all_scenarios.py

Set-Location ..\frontend
npm run build
```

Current expected backend result: all tests pass. The known non-blocking warnings are Starlette/httpx compatibility deprecation and Pydantic class-based `Config` deprecation.

## 8. What to Explain in a Demo

1. Start with the uncertainty distinction: timeout does not mean failure.
2. Show the agent retry and the two successful captures.
3. Open the case and point to the causal chain and Rs 25,000 exposure.
4. Explain that deterministic invariants detect the actual violation.
5. Show outcome memory as advisory historical context.
6. Approve the refund.
7. Explain the mode difference: simulation closes immediately; provider mode waits for webhook proof.
8. Send or describe `refund.processed`.
9. Show that the webhook is appended to the same stream and the same case becomes `ASSURED`.
10. Close by showing the broader workflow matrix: retry, refund, settlement, and dispute all use the same Assurance pipeline.

## 9. Honest Limitations

- Stores are in-memory and are lost on process restart.
- Webhook idempotency is process-local until moved to a database uniqueness constraint.
- Scenario data is controlled synthetic data, not proprietary production payment data.
- Current outcome memory is transparent historical scoring; a trained ML model should be introduced only after feature generation and evaluation are established.
- Provider webhook semantics must be mapped carefully: `refund.processed` should only mark `ASSURED` if it represents the required financial completion guarantee.
- Frontend demo metrics must be labeled as simulated unless backed by real transaction data.

## 10. Short Final Pitch

Assurance is a financial state verification layer for asynchronous payment systems. It does not merely detect that an event occurred. It asks whether the expected financial outcome actually happened, explains the causal chain when it did not, recommends a controlled response, and verifies that response through the same event stream.
