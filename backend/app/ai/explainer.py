from __future__ import annotations

from dataclasses import dataclass

from app.cases.assurance import AssuranceCase, RecommendedAction, ViolationType
from app.ai.explanation_catalog import EXPLANATION_CATALOG


@dataclass(frozen=True)
class GroundedExplanation:
    provider: str
    summary: str
    root_cause: str
    recommendation: str
    confidence: float
    evidence_event_ids: list[str]
    why_flagged: str = ""

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "summary": self.summary,
            "root_cause": self.root_cause,
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "evidence_event_ids": self.evidence_event_ids,
            "why_flagged": self.why_flagged,
        }


def explain_case(case: AssuranceCase) -> GroundedExplanation:
    """Produce a deterministic, evidence-bounded explanation."""
    exposure = f"Rs {case.exposure_inr:,.0f}"
    
    # 1. Fetch catalog semantics
    v_type = case.violation_type
    if v_type not in EXPLANATION_CATALOG:
        # Extreme fallback if a new enum was added but not to the catalog
        action = case.recommended_action.value if case.recommended_action else "ESCALATE"
        return GroundedExplanation(
            provider="grounded-deterministic-v1",
            summary=case.violation_description or "Anomalous event sequence detected.",
            root_cause=f"The deterministic invariant for {v_type.value if v_type else 'anomalous behavior'} was breached.",
            why_flagged="The reconstructed state machine did not match the required invariants.",
            recommendation=f"Recommended action: {action}.",
            confidence=case.confidence,
            evidence_event_ids=case.evidence_event_ids,
        )
        
    template = EXPLANATION_CATALOG[v_type]
    summary = template["what_happened"]
    root_cause = template["root_cause"]
    why_flagged = template["why_flagged"]
    
    # 2. Data Grounding (Interpolation)
    # E.g. for REFUND_SLA_BREACH, check if there's a REFUND_FAILED in the evidence/timeline
    if v_type == ViolationType.REFUND_SLA_BREACH:
        failed = [s for s in case.causal_chain if s.event_type == "payment.refund_failed"]
        completed = [s for s in case.causal_chain if s.event_type in ("payment.refund_completed", "payment.refund_processed")]
        if failed:
            root_cause += " Specifically, a refund failure event was detected."
        elif completed:
            root_cause += " Specifically, the refund eventually completed, but after the allowed deadline."
            
    # Can expand grounding logic here safely for other violations
    # For now, append exposure logic if applicable
    if case.financial_exposure and case.financial_exposure > 0:
        why_flagged += f" A monetary exposure of {exposure} was calculated."

    action = case.recommended_action.value if case.recommended_action else "ESCALATE"
    
    return GroundedExplanation(
        provider="grounded-deterministic-v1",
        summary=summary,
        root_cause=root_cause,
        why_flagged=why_flagged,
        recommendation=f"Recommended action: {action}.",
        confidence=case.confidence,
        evidence_event_ids=case.evidence_event_ids,
    )
