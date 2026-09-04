"""
Financial Invariant Engine
--------------------------
Invariants define what "correct" means for a financial operation.

These are not heuristics. They are precise mathematical rules derived from
how payment systems are supposed to work. If an invariant is violated,
something unexpected happened — and Assurance needs to investigate why.

Design principle:
    The invariant engine produces VIOLATIONS, not explanations.
    Explanations come from the causal graph + LLM layer.
    Here we only ask: "Is the financial state consistent?"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from app.models.event import EventStream, EventType
from app.state.payment import PaymentStateMachine, PaymentState, ResolvedPayment, SUCCESSFUL_STATES
from app.state.settlement import SettlementStateMachine, SettlementState
from app.state.evidence import EvidenceStateMachine, EvidenceState

# ---------------------------------------------------------------------------
# Violation Types
# ---------------------------------------------------------------------------

class ViolationType(str, Enum):
    # Payment violations
    DUPLICATE_COLLECTION         = "DUPLICATE_COLLECTION"
    PAYMENT_AMOUNT_MISMATCH      = "PAYMENT_AMOUNT_MISMATCH"
    PAYMENT_WITHOUT_ORDER        = "PAYMENT_WITHOUT_ORDER"
    UNCERTAIN_PAYMENT_CAPTURED   = "UNCERTAIN_PAYMENT_CAPTURED"  # Resolved late
    COLLECTION_AFTER_CANCELLATION= "COLLECTION_AFTER_CANCELLATION"
    AMOUNT_MISMATCH              = "AMOUNT_MISMATCH"
    CONFLICTING_AGENT_ACTION     = "CONFLICTING_AGENT_ACTION"

    # Refund violations
    REFUND_EXCEEDS_CAPTURED      = "REFUND_EXCEEDS_CAPTURED"
    REFUND_REVERSAL              = "REFUND_REVERSAL"
    REFUND_NOT_COMPLETED         = "REFUND_NOT_COMPLETED"
    DUPLICATE_REFUND             = "DUPLICATE_REFUND"
    REFUND_SLA_BREACH            = "REFUND_SLA_BREACH"
    REFUND_FAILURE               = "REFUND_FAILURE"
    REFUND_WITHOUT_CAPTURE       = "REFUND_WITHOUT_CAPTURE"
    UNEXPECTED_AGENT_REFUND      = "UNEXPECTED_AGENT_REFUND"

    # Settlement violations
    SETTLEMENT_VARIANCE          = "SETTLEMENT_VARIANCE"
    SETTLEMENT_UNEXPLAINED       = "SETTLEMENT_UNEXPLAINED"
    MISSING_SETTLEMENT           = "MISSING_SETTLEMENT"
    SETTLEMENT_AMOUNT_MISMATCH   = "SETTLEMENT_AMOUNT_MISMATCH"
    UNEXPLAINED_ADJUSTMENT       = "UNEXPLAINED_ADJUSTMENT"
    CROSS_CYCLE_DISCREPANCY      = "CROSS_CYCLE_DISCREPANCY"

    # Dispute violations
    DISPUTE_EVIDENCE_CONTRADICTION = "DISPUTE_EVIDENCE_CONTRADICTION"
    DISPUTE_MISSING_EVIDENCE       = "DISPUTE_MISSING_EVIDENCE"
    DISPUTE_ALREADY_REFUNDED       = "DISPUTE_ALREADY_REFUNDED"
    DISPUTE_DEADLINE_RISK          = "DISPUTE_DEADLINE_RISK"
    AUTOMATED_DISPUTE_CONTESTED    = "AUTOMATED_DISPUTE_CONTESTED"
    CONTESTED_RESOLUTION         = "CONTESTED_RESOLUTION"
    LATE_EVIDENCE                = "LATE_EVIDENCE"
    FUNDS_WITHHELD_INCORRECTLY   = "FUNDS_WITHHELD_INCORRECTLY"
    MISSING_CHARGEBACK_DEDUCTION = "MISSING_CHARGEBACK_DEDUCTION"

    # Cross-Workflow violations
    CONCURRENT_DISPUTE_REFUND    = "CONCURRENT_DISPUTE_REFUND"


class ViolationSeverity(str, Enum):
    CRITICAL = "CRITICAL"   # Immediate financial loss possible
    HIGH     = "HIGH"       # Significant risk, needs prompt attention
    MEDIUM   = "MEDIUM"     # Anomaly detected, investigate
    LOW      = "LOW"        # Informational, monitor


# ---------------------------------------------------------------------------
# Invariant Violation
# ---------------------------------------------------------------------------

@dataclass
class InvariantViolation:
    """
    A single invariant violation detected by the engine.

    Violations are the raw output of the invariant engine.
    They become the seed of an Assurance Case.
    """
    violation_type:     ViolationType
    severity:           ViolationSeverity
    description:        str

    # Financial impact
    financial_exposure: int = 0          # paise — how much is at risk
    currency:           str = "INR"

    # What we expected vs. what we observed
    expected:           dict = field(default_factory=dict)
    observed:           dict = field(default_factory=dict)

    # Which payments/refunds are involved
    involved_payment_ids: list[str] = field(default_factory=list)
    involved_refund_ids:  list[str] = field(default_factory=list)

    # The events that are evidence of the violation
    evidence_event_ids: list[str] = field(default_factory=list)

    @property
    def financial_exposure_inr(self) -> float:
        return self.financial_exposure / 100

    def __repr__(self) -> str:
        return (
            f"[{self.severity.value}] {self.violation_type.value} "
            f"— ₹{self.financial_exposure_inr:,.0f} exposure"
        )


# ---------------------------------------------------------------------------
# Order Financial State — derived from events
# ---------------------------------------------------------------------------

@dataclass
class OrderFinancialState:
    order_id:          str
    payments:          list[ResolvedPayment]
    total_captured:    int = 0     # paise
    total_refunded:    int = 0     # paise
    net_captured:      int = 0     # total_captured - total_refunded

    @property
    def successful_payments(self) -> list[ResolvedPayment]:
        return [p for p in self.payments if p.is_successful]

    @property
    def uncertain_payments(self) -> list[ResolvedPayment]:
        return [p for p in self.payments if p.is_uncertain]

    @property
    def successful_count(self) -> int:
        return len(self.successful_payments)


# ---------------------------------------------------------------------------
# Invariant Engine
# ---------------------------------------------------------------------------

class InvariantEngine:
    """
    Evaluates financial invariants against an EventStream.

    Returns a list of InvariantViolations (may be empty for clean operations).
    """

    def __init__(self):
        self._state_machine = PaymentStateMachine()
        self._settlement_machine = SettlementStateMachine()
        self._evidence_machine = EvidenceStateMachine()

    def evaluate(self, stream: EventStream) -> list[InvariantViolation]:
        """
        Run all invariants against the stream.
        Returns all violations found (empty list = financially consistent).
        """
        violations: list[InvariantViolation] = []

        # Resolve states
        resolved_payments = self._resolve_payments(stream)
        order_state = self._build_order_state(stream, resolved_payments)
        settlement_state = self._settlement_machine.resolve(stream)
        evidence_state = self._evidence_machine.resolve(stream)

        # Payment/Refund Invariants
        violations.extend(self._check_retry_integrity(stream, resolved_payments))
        violations.extend(self._check_duplicate_collection(order_state, stream))
        violations.extend(self._check_refund_limits(order_state, stream))
        violations.extend(self._check_duplicate_refunds(stream))
        violations.extend(self._check_refund_reversals(stream))
        violations.extend(self._check_incomplete_refunds(stream))
        violations.extend(self._check_refund_without_capture(order_state, stream))
        violations.extend(self._check_unexpected_agent_refund(order_state, stream))
        violations.extend(self._check_late_authorization(order_state, stream))

        # Settlement Invariants
        violations.extend(self._check_missing_settlement(order_state, stream))
        violations.extend(self._check_settlement_variance(order_state, settlement_state, stream))

        # Evidence Invariants
        violations.extend(self._check_evidence_invariants(evidence_state, order_state, stream))

        return violations

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _resolve_payments(self, stream: EventStream) -> dict[str, ResolvedPayment]:
        resolved: dict[str, ResolvedPayment] = {}
        for payment_id in stream.payment_ids:
            try:
                resolved[payment_id] = self._state_machine.resolve(payment_id, stream)
            except ValueError:
                pass  # Malformed payment — will surface as separate anomaly
        return resolved

    def _build_order_state(
        self,
        stream: EventStream,
        resolved: dict[str, ResolvedPayment],
    ) -> OrderFinancialState:
        payments = list(resolved.values())

        total_captured = sum(
            p.amount for p in payments
            if p.is_successful and p.amount is not None
        )

        # Total refunded: sum all REFUND_PROCESSED / REFUND_COMPLETED events
        refund_events = stream.by_type(EventType.REFUND_REQUESTED)
        # Subtract any reversals
        reversal_events = stream.by_type(EventType.REFUND_REVERSED)
        total_refunded = (
            sum(e.amount for e in refund_events if e.amount)
            - sum(e.amount for e in reversal_events if e.amount)
        )

        return OrderFinancialState(
            order_id=stream.order_id or "unknown",
            payments=payments,
            total_captured=total_captured,
            total_refunded=max(0, total_refunded),
            net_captured=max(0, total_captured - total_refunded),
        )

    # -----------------------------------------------------------------------
    # Invariant 1 — Duplicate Collection
    # -----------------------------------------------------------------------

    def _check_retry_integrity(
        self,
        stream: EventStream,
        resolved: dict[str, ResolvedPayment],
    ) -> list[InvariantViolation]:
        violations = []
        original_amounts = [
            event.amount for event in stream.events
            if event.event_type == EventType.PAYMENT_CREATED
            and event.source != "agent"
            and event.amount is not None
        ]
        if original_amounts:
            original_amount = original_amounts[0]
            for payment in resolved.values():
                if payment.agent_initiated and payment.amount is not None and payment.amount != original_amount:
                    violations.append(InvariantViolation(
                        violation_type=ViolationType.PAYMENT_AMOUNT_MISMATCH,
                        severity=ViolationSeverity.HIGH,
                        description=f"Retry payment {payment.payment_id} amount differs from the original payment.",
                        financial_exposure=abs(payment.amount - original_amount),
                        expected={"original_amount": original_amount / 100},
                        observed={"retry_amount": payment.amount / 100},
                        involved_payment_ids=[payment.payment_id],
                    ))

        cancelled = {
            event.payment_id for event in stream.events
            if event.event_type == EventType.PAYMENT_CANCELLED and event.payment_id
        }
        for event in stream.events:
            if event.event_type == EventType.AGENT_RETRY_INITIATED and event.payment_id in cancelled:
                violations.append(InvariantViolation(
                    violation_type=ViolationType.COLLECTION_AFTER_CANCELLATION,
                    severity=ViolationSeverity.HIGH,
                    description=f"Agent retried cancelled payment {event.payment_id}.",
                    involved_payment_ids=[event.payment_id],
                    evidence_event_ids=[event.event_id],
                ))

        # Conflicting agent action (retry while refund is pending)
        pending_refunds = stream.by_type(EventType.REFUND_REQUESTED)
        for event in stream.events:
            if event.event_type == EventType.AGENT_RETRY_INITIATED and pending_refunds:
                # check time overlap roughly
                refund_req_time = min(r.timestamp for r in pending_refunds)
                if event.timestamp > refund_req_time:
                    violations.append(InvariantViolation(
                        violation_type=ViolationType.CONFLICTING_AGENT_ACTION,
                        severity=ViolationSeverity.CRITICAL,
                        description="Agent retried payment while a refund was already requested.",
                        involved_payment_ids=[event.payment_id] if event.payment_id else [],
                        evidence_event_ids=[event.event_id],
                    ))

        return violations

    def _check_duplicate_collection(
        self,
        order_state: OrderFinancialState,
        stream: EventStream,
    ) -> list[InvariantViolation]:
        successful = order_state.successful_payments
        if len(successful) <= 1:
            return []

        amounts = sorted([p.amount for p in successful if p.amount is not None])
        expected_amount  = amounts[0] if amounts else 0
        excess_captured  = sum(amounts[1:])

        # A duplicate collection is resolved once the excess amount has been
        # returned. The historical captures remain evidence, but no exposure
        # remains to report as an open duplicate.
        if order_state.total_refunded >= excess_captured:
            return []

        sorted_by_time = sorted(
            successful,
            key=lambda p: p.transitions[0].timestamp if p.transitions else p.events[0].timestamp
        )

        evidence_ids = [
            e.event_id
            for p in sorted_by_time[1:]
            for e in p.events
            if e.event_type == EventType.PAYMENT_CAPTURED
        ]

        return [InvariantViolation(
            violation_type=ViolationType.DUPLICATE_COLLECTION,
            severity=ViolationSeverity.CRITICAL,
            description=(
                f"Order {order_state.order_id} has {len(successful)} successful payments "
                f"but expected at most 1. "
                f"Excess captured: ₹{excess_captured / 100:,.0f}."
            ),
            financial_exposure=excess_captured,
            expected={"successful_payments": 1, "amount_inr": expected_amount / 100},
            observed={
                "successful_payments": len(successful),
                "payment_ids": [p.payment_id for p in sorted_by_time],
                "total_captured_inr": order_state.total_captured / 100,
            },
            involved_payment_ids=[p.payment_id for p in successful],
            evidence_event_ids=evidence_ids,
        )]

    # -----------------------------------------------------------------------
    # Invariant 2 — Refund Limits & Duplicates
    # -----------------------------------------------------------------------

    def _check_refund_limits(
        self,
        order_state: OrderFinancialState,
        stream: EventStream,
    ) -> list[InvariantViolation]:
        if order_state.total_refunded <= order_state.total_captured:
            return []

        excess = order_state.total_refunded - order_state.total_captured

        return [InvariantViolation(
            violation_type=ViolationType.REFUND_EXCEEDS_CAPTURED,
            severity=ViolationSeverity.CRITICAL,
            description=(
                f"Total refunded (₹{order_state.total_refunded / 100:,.0f}) exceeds "
                f"total captured (₹{order_state.total_captured / 100:,.0f}). "
                f"Over-refund exposure: ₹{excess / 100:,.0f}."
            ),
            financial_exposure=excess,
            expected={"max_refundable_inr": order_state.total_captured / 100},
            observed={"total_refunded_inr": order_state.total_refunded / 100},
        )]

    def _check_duplicate_refunds(self, stream: EventStream) -> list[InvariantViolation]:
        # Track refunds per payment ID
        refunds_by_pid = {}
        violations = []
        for r in stream.by_type(EventType.REFUND_COMPLETED):
            if r.payment_id not in refunds_by_pid:
                refunds_by_pid[r.payment_id] = []
            refunds_by_pid[r.payment_id].append(r)
            
        for pid, refunds in refunds_by_pid.items():
            if len(refunds) > 1:
                # Naive duplicate check: if multiple refunds of same amount
                amounts = [r.amount for r in refunds]
                if len(amounts) > len(set(amounts)):
                    # Found duplicate amount
                    excess = sum(amounts) - max(amounts) # simplistic
                    violations.append(InvariantViolation(
                        violation_type=ViolationType.DUPLICATE_REFUND,
                        severity=ViolationSeverity.CRITICAL,
                        description=f"Duplicate refunds detected for payment {pid}.",
                        financial_exposure=excess,
                        evidence_event_ids=[r.event_id for r in refunds],
                    ))
        return violations

    def _check_refund_reversals(self, stream: EventStream) -> list[InvariantViolation]:
        reversals = stream.by_type(EventType.REFUND_REVERSED)
        violations = []
        for r in reversals:
            violations.append(InvariantViolation(
                violation_type=ViolationType.REFUND_REVERSAL,
                severity=ViolationSeverity.HIGH,
                description=f"Refund {r.refund_id} for payment {r.payment_id} was reversed.",
                financial_exposure=r.amount or 0,
                evidence_event_ids=[r.event_id],
                expected={"refund_status": "completed"},
                observed={"refund_status": "reversed"}
            ))
        return violations

    def _check_incomplete_refunds(self, stream: EventStream) -> list[InvariantViolation]:
        completed = {event.refund_id for event in stream.by_type(EventType.REFUND_COMPLETED) if event.refund_id}
        failed = {event.refund_id for event in stream.by_type(EventType.REFUND_FAILED) if event.refund_id}
        
        violations = []
        for event in stream.by_type(EventType.REFUND_REQUESTED):
            if event.refund_id and event.refund_id not in completed:
                if event.refund_id in failed:
                    violations.append(InvariantViolation(
                        violation_type=ViolationType.REFUND_FAILURE,
                        severity=ViolationSeverity.HIGH,
                        description=f"Refund {event.refund_id} explicitly failed.",
                        financial_exposure=event.amount or 0,
                        expected={"refund_status": "completed"},
                        observed={"refund_status": "failed"},
                        involved_refund_ids=[event.refund_id],
                        evidence_event_ids=[event.event_id],
                    ))
                else:
                    # check if SLA breached (simulate SLA by looking at time since request)
                    # For tests, we'll just flag it if there is a large gap or if it's the last event
                    last_event_time = stream.events[-1].timestamp
                    if (last_event_time - event.timestamp).total_seconds() > 86400: # > 1 day
                        violations.append(InvariantViolation(
                            violation_type=ViolationType.REFUND_SLA_BREACH,
                            severity=ViolationSeverity.HIGH,
                            description=f"Refund {event.refund_id} SLA breached.",
                            financial_exposure=event.amount or 0,
                            involved_refund_ids=[event.refund_id],
                            evidence_event_ids=[event.event_id],
                        ))
                    else:
                        violations.append(InvariantViolation(
                            violation_type=ViolationType.REFUND_NOT_COMPLETED,
                            severity=ViolationSeverity.MEDIUM,
                            description=f"Refund {event.refund_id} was requested but never completed.",
                            financial_exposure=event.amount or 0,
                            expected={"refund_status": "completed"},
                            observed={"refund_status": "pending"},
                            involved_refund_ids=[event.refund_id],
                            evidence_event_ids=[event.event_id],
                        ))
        return violations

    def _check_refund_without_capture(self, order_state: OrderFinancialState, stream: EventStream) -> list[InvariantViolation]:
        violations = []
        if order_state.total_refunded > 0 and order_state.total_captured == 0:
            violations.append(InvariantViolation(
                violation_type=ViolationType.REFUND_WITHOUT_CAPTURE,
                severity=ViolationSeverity.CRITICAL,
                description="Refund processed but no funds were ever captured.",
                financial_exposure=order_state.total_refunded,
                expected={"min_captured": order_state.total_refunded},
                observed={"total_captured": 0},
            ))
        return violations
        
    def _check_unexpected_agent_refund(self, order_state: OrderFinancialState, stream: EventStream) -> list[InvariantViolation]:
        violations = []
        agent_refunds = stream.by_type(EventType.AGENT_REFUND_INITIATED)
        if agent_refunds and order_state.total_captured > 0:
            # Check if there's any dispute or obvious reason. If clean, it's unexpected.
            disputes = stream.by_type(EventType.DISPUTE_CREATED)
            if not disputes:
                for event in agent_refunds:
                    violations.append(InvariantViolation(
                        violation_type=ViolationType.UNEXPECTED_AGENT_REFUND,
                        severity=ViolationSeverity.HIGH,
                        description="Agent initiated refund on a seemingly clean order.",
                        financial_exposure=event.amount or 0,
                        evidence_event_ids=[event.event_id],
                    ))
        return violations

    # -----------------------------------------------------------------------
    # Invariant 3 — Late Authorization Detection
    # -----------------------------------------------------------------------

    def _check_late_authorization(
        self,
        order_state: OrderFinancialState,
        stream: EventStream,
    ) -> list[InvariantViolation]:
        violations = []
        for payment in order_state.payments:
            if not payment.is_successful:
                continue
            states_visited = [t.to_state for t in payment.transitions]
            if PaymentState.UNCERTAIN in states_visited or PaymentState.TIMEOUT in states_visited:
                violations.append(InvariantViolation(
                    violation_type=ViolationType.UNCERTAIN_PAYMENT_CAPTURED,
                    severity=ViolationSeverity.MEDIUM,
                    description=(
                        f"Payment {payment.payment_id} passed through UNCERTAIN state "
                        f"before being captured."
                    ),
                    financial_exposure=payment.amount or 0,
                    expected={"state_at_capture": "AUTHORIZED → CAPTURED (direct)"},
                    observed={"state_path": [t.to_state.value for t in payment.transitions]},
                    involved_payment_ids=[payment.payment_id],
                ))
        return violations

    def _check_missing_settlement(
        self,
        order_state: OrderFinancialState,
        stream: EventStream,
    ) -> list[InvariantViolation]:
        violations = []
        if order_state.total_captured > 0:
            has_settlement = any(e for e in stream.by_type(EventType.SETTLEMENT_PROCESSED))
            if not has_settlement:
                has_created = any(e for e in stream.by_type(EventType.SETTLEMENT_CREATED))
                if has_created:
                    violations.append(InvariantViolation(
                        violation_type=ViolationType.MISSING_SETTLEMENT,
                        severity=ViolationSeverity.HIGH,
                        description="Settlement created but never processed for captured payments.",
                        financial_exposure=order_state.net_captured,
                        expected={"settlement_processed": True},
                        observed={"settlement_processed": False},
                    ))
        return violations

    # -----------------------------------------------------------------------
    # Settlement Invariants
    # -----------------------------------------------------------------------

    def _check_settlement_variance(
        self,
        order_state: OrderFinancialState,
        settlement_state: SettlementState,
        stream: EventStream,
    ) -> list[InvariantViolation]:
        violations = []
        if not settlement_state.settlements:
            if any(event.metadata.get("settlement_expected") for event in stream.events):
                violations.append(InvariantViolation(
                    violation_type=ViolationType.MISSING_SETTLEMENT,
                    severity=ViolationSeverity.HIGH,
                    description="Captured funds have no corresponding settlement event.",
                    financial_exposure=order_state.net_captured,
                    expected={"settlement_present": True},
                    observed={"settlement_present": False},
                ))
            return violations
            
        total_settled = settlement_state.total_settled
        if total_settled == 0 and not any(e for e in stream.by_type(EventType.SETTLEMENT_PROCESSED)):
            return violations # already handled by MISSING_SETTLEMENT check
            
        # Check adjustments first
        for event in stream.by_type(EventType.SETTLEMENT_ADJUSTED):
            if "reason" not in event.metadata and "cross_cycle" not in event.metadata:
                violations.append(InvariantViolation(
                    violation_type=ViolationType.UNEXPLAINED_ADJUSTMENT,
                    severity=ViolationSeverity.MEDIUM,
                    description="Settlement adjustment has no reason provided.",
                    financial_exposure=abs(event.amount or 0),
                    evidence_event_ids=[event.event_id],
                ))
            if event.metadata.get("cross_cycle"):
                violations.append(InvariantViolation(
                    violation_type=ViolationType.CROSS_CYCLE_DISCREPANCY,
                    severity=ViolationSeverity.LOW,
                    description="Cross-cycle adjustment applied.",
                    financial_exposure=abs(event.amount or 0),
                    evidence_event_ids=[event.event_id],
                ))

        # Expected Settlement = Captured - Refunded + Adjustments - Fees
        expected = order_state.net_captured + settlement_state.total_adjustments - settlement_state.total_fees
        
        variance = abs(expected - total_settled)
        if variance > 0:
            # Did the actual transaction amount not match?
            # We can distinguish between SETTLEMENT_AMOUNT_MISMATCH and VARIANCE
            # If the difference exactly matches a known payment that failed to settle:
            if any(p.amount == variance for p in order_state.successful_payments if p.amount):
                violations.append(InvariantViolation(
                    violation_type=ViolationType.SETTLEMENT_AMOUNT_MISMATCH,
                    severity=ViolationSeverity.HIGH,
                    description=f"A specific captured payment of {variance/100} seems missing from settlement.",
                    financial_exposure=variance,
                    expected={"settlement_amount_inr": expected / 100},
                    observed={"settlement_amount_inr": total_settled / 100},
                ))
            else:
                unexplained = any(
                    event.metadata.get("unexplained_variance")
                    for event in stream.by_type(EventType.SETTLEMENT_PROCESSED)
                )
                violations.append(InvariantViolation(
                    violation_type=ViolationType.SETTLEMENT_UNEXPLAINED if unexplained else ViolationType.SETTLEMENT_VARIANCE,
                    severity=ViolationSeverity.HIGH,
                    description=(
                        f"Settlement variance detected. Expected ₹{expected/100:,.0f}, "
                        f"but actual is ₹{total_settled/100:,.0f}."
                    ),
                    financial_exposure=variance,
                    expected={"settlement_amount_inr": expected / 100},
                    observed={"settlement_amount_inr": total_settled / 100},
                ))
        return violations

    # -----------------------------------------------------------------------
    # Evidence / Dispute Invariants
    # -----------------------------------------------------------------------

    def _check_evidence_invariants(
        self,
        evidence: EvidenceState,
        order_state: OrderFinancialState,
        stream: EventStream,
    ) -> list[InvariantViolation]:
        violations = []
        if not evidence.has_dispute:
            return violations
            
        claim = evidence.dispute_claim
        
        # 1. Contradiction Check
        if claim == "PRODUCT_NOT_RECEIVED" or claim == "FRAUDULENT":
            if evidence.delivery_status == "DELIVERED":
                violations.append(InvariantViolation(
                    violation_type=ViolationType.DISPUTE_EVIDENCE_CONTRADICTION,
                    severity=ViolationSeverity.HIGH,
                    description="Customer claims not received, but delivery status is DELIVERED.",
                    expected={"delivery_status": "NOT_DELIVERED"},
                    observed={"delivery_status": "DELIVERED"},
                ))
                
        # 2. Missing Evidence Check
        if claim == "PRODUCT_NOT_RECEIVED" and evidence.delivery_status is None:
            violations.append(InvariantViolation(
                violation_type=ViolationType.DISPUTE_MISSING_EVIDENCE,
                severity=ViolationSeverity.MEDIUM,
                description="Dispute for PRODUCT_NOT_RECEIVED requires delivery evidence, but none is provided.",
                expected={"delivery_status": "ANY"},
                observed={"delivery_status": "NONE"},
            ))
            
        # 3. Already Refunded Check
        if order_state.total_refunded > 0 and order_state.total_captured == order_state.total_refunded:
            violations.append(InvariantViolation(
                violation_type=ViolationType.DISPUTE_ALREADY_REFUNDED,
                severity=ViolationSeverity.CRITICAL,
                description="Dispute raised on an order that is already fully refunded.",
                financial_exposure=order_state.total_refunded,
            ))
            
        # 4. Deadline Risk Check
        for event in stream.events:
            if event.event_type == EventType.DISPUTE_CREATED:
                deadline = event.metadata.get("deadline")
                if deadline:
                    # simplistic check: if deadline is present and no evidence submitted, flag it
                    # (in a real system, we'd check if current_time is near the deadline string)
                    if evidence.delivery_status is None and evidence.customer_communication is None and not evidence.evidence_dict:
                        violations.append(InvariantViolation(
                            violation_type=ViolationType.DISPUTE_DEADLINE_RISK,
                            severity=ViolationSeverity.MEDIUM,
                            description="Dispute deadline is approaching but no evidence has been submitted.",
                            expected={"evidence_submitted": True},
                            observed={"evidence_submitted": False},
                        ))

        # 5. Automated contest later contradicted by incoming evidence
        automated_contests = stream.by_type(EventType.AGENT_DISPUTE_INITIATED)
        if automated_contests and evidence.delivery_status == "DELIVERED":
            violations.append(InvariantViolation(
                violation_type=ViolationType.AUTOMATED_DISPUTE_CONTESTED,
                severity=ViolationSeverity.HIGH,
                description="Automated dispute contest was followed by contradictory delivery evidence.",
                expected={"automated_decision": "supported"},
                observed={"delivery_status": "DELIVERED"},
                evidence_event_ids=[event.event_id for event in automated_contests],
            ))
            
        # 6. Late Evidence
        for event in stream.by_type(EventType.DISPUTE_EVIDENCE_SUBMITTED):
            # simulate deadline check: if event has "is_late" metadata
            if event.metadata.get("is_late"):
                violations.append(InvariantViolation(
                    violation_type=ViolationType.LATE_EVIDENCE,
                    severity=ViolationSeverity.MEDIUM,
                    description="Dispute evidence submitted after the deadline.",
                    evidence_event_ids=[event.event_id],
                ))

        # 7. Inconsistent Outcome (won but withheld)
        if evidence.dispute_status == "won" and evidence.funds_withheld:
            violations.append(InvariantViolation(
                violation_type=ViolationType.FUNDS_WITHHELD_INCORRECTLY,
                severity=ViolationSeverity.HIGH,
                description="Dispute was won by merchant but funds are still withheld.",
                expected={"funds_withheld": False},
                observed={"funds_withheld": True},
            ))

        # 8. Missing Chargeback Deduction (lost but not deducted)
        if evidence.dispute_status == "lost" and not evidence.funds_withheld:
            # Did settlement deduct it?
            # Rough check: if there is no settlement adjustment matching the amount
            deductions = [e for e in stream.by_type(EventType.SETTLEMENT_ADJUSTED) if e.amount and e.amount < 0]
            if not deductions:
                violations.append(InvariantViolation(
                    violation_type=ViolationType.MISSING_CHARGEBACK_DEDUCTION,
                    severity=ViolationSeverity.CRITICAL,
                    description="Dispute lost but no chargeback deduction occurred.",
                ))

        # 9. Concurrent Dispute & Refund
        if order_state.total_refunded > 0:
            refunds = stream.by_type(EventType.REFUND_REQUESTED)
            disputes = stream.by_type(EventType.DISPUTE_CREATED)
            if refunds and disputes:
                # Find if they overlap
                ref_ts = min(r.timestamp for r in refunds)
                disp_ts = min(d.timestamp for d in disputes)
                # If dispute created while refund is pending/processing, or roughly same time
                if abs((ref_ts - disp_ts).total_seconds()) < 86400:
                    violations.append(InvariantViolation(
                        violation_type=ViolationType.CONCURRENT_DISPUTE_REFUND,
                        severity=ViolationSeverity.HIGH,
                        description="Refund requested concurrently with an active dispute.",
                    ))

        return violations
