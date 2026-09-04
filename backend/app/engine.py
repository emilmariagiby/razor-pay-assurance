"""
Assurance Engine
----------------
The heart of the system. Takes an EventStream and produces Assurance Cases.

Pipeline:
    EventStream
        → PaymentStateMachine   (resolve each payment's current state)
        → InvariantEngine       (detect financial invariant violations)
        → CausalGraphBuilder    (reconstruct WHY violations happened)
        → CausalChainExtractor  (linearize the causal graph into readable steps)
        → AssuranceCaseBuilder  (produce structured cases for the API/UI)

Usage:
    engine = AssuranceEngine()
    cases  = engine.investigate(stream)
"""

from __future__ import annotations

from typing import Optional
from datetime import datetime

import networkx as nx

from app.models.event import EventStream, EventType, FinancialEvent
from app.state.payment import PaymentStateMachine, SUCCESSFUL_STATES
from app.invariants.payment import InvariantEngine, InvariantViolation, ViolationType
from app.graph.causal import CausalGraphBuilder, CausalChainExtractor
from app.cases.assurance import (
    AssuranceCase,
    AssuranceCaseStatus,
    CaseTimelineStep,
    RecommendedAction,
    ViolationType as CaseViolationType,
)


class AssuranceEngine:
    """
    Orchestrates the full assurance pipeline.

    For each EventStream, produces zero or more AssuranceCases.
    Zero cases = all financial invariants hold = 🟢 ASSURED.
    """

    def __init__(self) -> None:
        self._state_machine     = PaymentStateMachine()
        self._invariant_engine  = InvariantEngine()
        self._graph_builder     = CausalGraphBuilder()
        self._chain_extractor   = CausalChainExtractor()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def investigate(self, stream: EventStream) -> list[AssuranceCase]:
        """
        Run the full assurance pipeline on a stream of financial events.

        Returns a list of AssuranceCases (empty = no violations detected).
        """
        # Step 1 — Resolve all payment states
        payments = {}
        for pid in stream.payment_ids:
            try:
                payments[pid] = self._state_machine.resolve(pid, stream)
            except ValueError:
                pass

        # Step 2 — Check all financial invariants
        violations = self._invariant_engine.evaluate(stream)

        if not violations:
            return []  # Clean bill of health

        # Step 3 — Build causal graph (once, shared across all violations)
        graph = self._graph_builder.build(stream)

        # Step 4 — Build an AssuranceCase for each violation
        cases = []
        for violation in violations:
            case = self._build_case(violation, stream, graph, payments)
            cases.append(case)

        return cases

    # ------------------------------------------------------------------
    # Case Builder
    # ------------------------------------------------------------------

    def _build_case(
        self,
        violation: InvariantViolation,
        stream:    EventStream,
        graph:     nx.DiGraph,
        payments:  dict,
    ) -> AssuranceCase:
        """
        Turn a raw InvariantViolation into a rich AssuranceCase.
        """
        # Map invariant violation type → case violation type
        v_type = self._map_violation_type(violation.violation_type)

        # Find the target event for causal chain extraction
        target_event_id = self._find_target_event(violation, stream, payments)

        # Extract causal chain
        if target_event_id and target_event_id in graph:
            chain_obj = self._chain_extractor.extract(graph, stream, target_event_id)
            causal_summary = chain_obj.summary
            causal_steps   = self._chain_to_steps(chain_obj.steps)
        else:
            causal_summary = violation.description
            causal_steps   = []

        # Determine recommendation
        action, detail, needs_approval = self._recommend(violation, payments)

        # Confidence: for now, deterministic engine = very high confidence
        # on structural violations. UNCERTAIN_PAYMENT_CAPTURED is lower.
        confidence = self._compute_confidence(violation)

        # Determine workflow
        workflow = self._determine_workflow(violation.violation_type)

        case = AssuranceCase(
            workflow=workflow,
            violation_type=v_type,
            violation_description=violation.description,
            severity=violation.severity.value,
            order_id=stream.order_id,
            merchant_id=stream.merchant_id,
            expected_state=violation.expected,
            observed_state=violation.observed,
            financial_exposure=violation.financial_exposure, # fallback
            confidence=confidence,
            causal_summary=causal_summary,
            causal_chain=causal_steps,
            evidence_event_ids=violation.evidence_event_ids,
            recommended_action=action,
            recommendation_detail=detail,
            requires_human_approval=needs_approval,
            status=AssuranceCaseStatus.OPEN,
        )
        # Standardize Exposure
        from app.cases.exposure import ExposureCalculator
        exposure = ExposureCalculator().calculate(case, stream)
        case.financial_exposure = exposure.gross_exposure
        case.exposure_details = exposure.to_dict()

        return case

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _map_violation_type(self, vt: ViolationType) -> CaseViolationType:
        mapping = {
            ViolationType.DUPLICATE_COLLECTION:         CaseViolationType.DUPLICATE_COLLECTION,
            ViolationType.PAYMENT_AMOUNT_MISMATCH:      CaseViolationType.PAYMENT_AMOUNT_MISMATCH,
            ViolationType.UNCERTAIN_PAYMENT_CAPTURED:   CaseViolationType.UNCERTAIN_PAYMENT_CAPTURED,
            ViolationType.REFUND_EXCEEDS_CAPTURED:      CaseViolationType.REFUND_EXCEEDS_CAPTURED,
            ViolationType.REFUND_REVERSAL:              CaseViolationType.REFUND_REVERSAL,
            ViolationType.REFUND_NOT_COMPLETED:         CaseViolationType.REFUND_NOT_COMPLETED,
            ViolationType.DUPLICATE_REFUND:             CaseViolationType.DUPLICATE_REFUND,
            ViolationType.SETTLEMENT_VARIANCE:          CaseViolationType.SETTLEMENT_VARIANCE,
            ViolationType.SETTLEMENT_UNEXPLAINED:       CaseViolationType.SETTLEMENT_UNEXPLAINED,
            ViolationType.DISPUTE_EVIDENCE_CONTRADICTION: CaseViolationType.DISPUTE_EVIDENCE_CONTRADICTION,
            ViolationType.DISPUTE_MISSING_EVIDENCE:     CaseViolationType.DISPUTE_MISSING_EVIDENCE,
            ViolationType.DISPUTE_ALREADY_REFUNDED:     CaseViolationType.DISPUTE_ALREADY_REFUNDED,
            ViolationType.DISPUTE_DEADLINE_RISK:        CaseViolationType.DISPUTE_DEADLINE_RISK,
            ViolationType.AUTOMATED_DISPUTE_CONTESTED:  CaseViolationType.AUTOMATED_DISPUTE_CONTESTED,
            
            # New types
            ViolationType.COLLECTION_AFTER_CANCELLATION: CaseViolationType.COLLECTION_AFTER_CANCELLATION,
            ViolationType.AMOUNT_MISMATCH:              CaseViolationType.AMOUNT_MISMATCH,
            ViolationType.CONFLICTING_AGENT_ACTION:     CaseViolationType.CONFLICTING_AGENT_ACTION,
            ViolationType.REFUND_SLA_BREACH:            CaseViolationType.REFUND_SLA_BREACH,
            ViolationType.REFUND_FAILURE:               CaseViolationType.REFUND_FAILURE,
            ViolationType.REFUND_WITHOUT_CAPTURE:       CaseViolationType.REFUND_WITHOUT_CAPTURE,
            ViolationType.UNEXPECTED_AGENT_REFUND:      CaseViolationType.UNEXPECTED_AGENT_REFUND,
            ViolationType.MISSING_SETTLEMENT:           CaseViolationType.MISSING_SETTLEMENT,
            ViolationType.SETTLEMENT_AMOUNT_MISMATCH:   CaseViolationType.SETTLEMENT_AMOUNT_MISMATCH,
            ViolationType.UNEXPLAINED_ADJUSTMENT:       CaseViolationType.UNEXPLAINED_ADJUSTMENT,
            ViolationType.CROSS_CYCLE_DISCREPANCY:      CaseViolationType.CROSS_CYCLE_DISCREPANCY,
            ViolationType.CONTESTED_RESOLUTION:         CaseViolationType.CONTESTED_RESOLUTION,
            ViolationType.LATE_EVIDENCE:                CaseViolationType.LATE_EVIDENCE,
            ViolationType.FUNDS_WITHHELD_INCORRECTLY:   CaseViolationType.FUNDS_WITHHELD_INCORRECTLY,
            ViolationType.MISSING_CHARGEBACK_DEDUCTION: CaseViolationType.MISSING_CHARGEBACK_DEDUCTION,
            ViolationType.CONCURRENT_DISPUTE_REFUND:    CaseViolationType.CONCURRENT_DISPUTE_REFUND,
        }
        return mapping.get(vt, CaseViolationType.DUPLICATE_COLLECTION)

    def _find_target_event(
        self,
        violation: InvariantViolation,
        stream:    EventStream,
        payments:  dict,
    ) -> Optional[str]:
        """
        Find the event ID that represents the 'outcome' of the violation —
        the event we trace backwards from in the causal graph.
        """
        if violation.violation_type == ViolationType.DUPLICATE_COLLECTION:
            # Target the retry payment (agent initiated) if possible, otherwise the last capture
            captures = stream.by_type(EventType.PAYMENT_CAPTURED)
            for p in payments.values():
                if p.is_successful and p.agent_initiated and p.caused_by_event_id:
                    agent_caps = [c for c in captures if c.payment_id == p.payment_id]
                    if agent_caps:
                        return agent_caps[-1].event_id
            
            captures = sorted(captures, key=lambda e: e.timestamp)
            if len(captures) >= 2:
                return captures[-1].event_id
            elif captures:
                return captures[0].event_id

        if violation.violation_type == ViolationType.UNCERTAIN_PAYMENT_CAPTURED:
            # Target = the capture event of the payment that went through UNCERTAIN
            if violation.involved_payment_ids:
                pid = violation.involved_payment_ids[0]
                captures = [
                    e for e in stream.by_type(EventType.PAYMENT_CAPTURED)
                    if e.payment_id == pid
                ]
                if captures:
                    return captures[0].event_id

        if violation.violation_type == ViolationType.SETTLEMENT_VARIANCE:
            settlements = stream.by_type(EventType.SETTLEMENT_PROCESSED)
            if settlements:
                return settlements[-1].event_id

        if violation.violation_type in (
            ViolationType.DISPUTE_EVIDENCE_CONTRADICTION,
            ViolationType.DISPUTE_MISSING_EVIDENCE,
            ViolationType.DISPUTE_ALREADY_REFUNDED,
            ViolationType.DISPUTE_DEADLINE_RISK,
        ):
            disputes = stream.by_type(EventType.DISPUTE_CREATED)
            if disputes:
                return disputes[-1].event_id

        if violation.evidence_event_ids:
            return violation.evidence_event_ids[0]

        return None

    def _chain_to_steps(self, steps) -> list[CaseTimelineStep]:
        result = []
        for step in steps:
            result.append(CaseTimelineStep(
                timestamp=step.event.timestamp,
                event_type=step.event.event_type,
                description=step.explanation,
                payment_id=step.event.payment_id,
                amount_inr=step.event.amount_inr,
            ))
        return result

    def _recommend(
        self,
        violation: InvariantViolation,
        payments:  dict,
    ) -> tuple[RecommendedAction, str, bool]:
        """Return (action, detail, requires_human_approval)."""

        if violation.violation_type == ViolationType.DUPLICATE_COLLECTION:
            duplicate_ids = violation.involved_payment_ids
            agent_payment = next(
                (p for p in payments.values()
                 if p.payment_id in duplicate_ids and p.agent_initiated),
                None,
            )
            if agent_payment:
                detail = (
                    f"Refund {agent_payment.payment_id} (₹{agent_payment.amount_inr:,.0f}) "
                    f"— this was the agent-initiated retry payment."
                )
            else:
                detail = (
                    f"Refund the most recently captured duplicate payment. "
                    f"₹{violation.financial_exposure_inr:,.0f} at risk."
                )
            return RecommendedAction.REFUND_DUPLICATE, detail, True

        if violation.violation_type == ViolationType.REFUND_EXCEEDS_CAPTURED:
            return (
                RecommendedAction.ESCALATE,
                "Over-refund detected. Escalate to finance team for manual review.",
                True,
            )

        if violation.violation_type == ViolationType.DUPLICATE_REFUND:
            return (
                RecommendedAction.CANCEL_REFUND,
                "Cancel duplicate refund request to prevent double refund.",
                True,
            )

        if violation.violation_type == ViolationType.REFUND_REVERSAL:
            return (
                RecommendedAction.ESCALATE,
                "Refund reversal after completion. Customer impact likely. Escalate.",
                True,
            )

        if violation.violation_type == ViolationType.UNCERTAIN_PAYMENT_CAPTURED:
            return (
                RecommendedAction.MONITOR,
                "Late authorization detected. Monitor for associated retry payments.",
                False,
            )

        if violation.violation_type == ViolationType.SETTLEMENT_VARIANCE:
            return (
                RecommendedAction.ESCALATE,
                "Unexplained settlement variance detected. Requires finance reconciliation.",
                True,
            )

        if violation.violation_type == ViolationType.DISPUTE_EVIDENCE_CONTRADICTION:
            return (
                RecommendedAction.CONTEST_DISPUTE,
                "Contest dispute with available contradictory evidence (e.g., delivery confirmed).",
                True,
            )
            
        if violation.violation_type == ViolationType.DISPUTE_MISSING_EVIDENCE:
            return (
                RecommendedAction.ESCALATE,
                "Request additional evidence from merchant before deadline.",
                True,
            )
            
        if violation.violation_type == ViolationType.DISPUTE_ALREADY_REFUNDED:
            return (
                RecommendedAction.CONTEST_DISPUTE,
                "Contest dispute automatically: order was already fully refunded.",
                False, # safe to auto contest
            )
            
        if violation.violation_type == ViolationType.DISPUTE_DEADLINE_RISK:
            return (
                RecommendedAction.ESCALATE,
                "Dispute deadline approaching. Urgent review required.",
                True,
            )

        return RecommendedAction.ESCALATE, "Investigate manually.", True

    def _compute_confidence(self, violation: InvariantViolation) -> float:
        high_confidence = {
            ViolationType.DUPLICATE_COLLECTION,
            ViolationType.REFUND_EXCEEDS_CAPTURED,
            ViolationType.REFUND_REVERSAL,
            ViolationType.DUPLICATE_REFUND,
            ViolationType.DISPUTE_EVIDENCE_CONTRADICTION,
            ViolationType.DISPUTE_ALREADY_REFUNDED,
        }
        medium_confidence = {
            ViolationType.UNCERTAIN_PAYMENT_CAPTURED,
            ViolationType.SETTLEMENT_VARIANCE,
            ViolationType.DISPUTE_MISSING_EVIDENCE,
            ViolationType.DISPUTE_DEADLINE_RISK,
        }

        if violation.violation_type in high_confidence:
            return 0.97
        if violation.violation_type in medium_confidence:
            return 0.74
        return 0.85

    def _determine_workflow(self, vt: ViolationType) -> str:
        mapping = {
            ViolationType.DUPLICATE_COLLECTION:         "retry",
            ViolationType.UNCERTAIN_PAYMENT_CAPTURED:   "retry",
            ViolationType.REFUND_EXCEEDS_CAPTURED:      "refund",
            ViolationType.REFUND_REVERSAL:              "refund",
            ViolationType.REFUND_NOT_COMPLETED:         "refund",
            ViolationType.DUPLICATE_REFUND:             "refund",
            ViolationType.SETTLEMENT_VARIANCE:          "settlement",
            ViolationType.SETTLEMENT_UNEXPLAINED:       "settlement",
            ViolationType.DISPUTE_EVIDENCE_CONTRADICTION: "dispute",
            ViolationType.DISPUTE_MISSING_EVIDENCE:     "dispute",
            ViolationType.DISPUTE_ALREADY_REFUNDED:     "dispute",
            ViolationType.DISPUTE_DEADLINE_RISK:        "dispute",
            ViolationType.AUTOMATED_DISPUTE_CONTESTED:  "dispute",
        }
        return mapping.get(vt, "retry")
