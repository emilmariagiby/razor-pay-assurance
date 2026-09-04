from __future__ import annotations

from dataclasses import dataclass

from app.cases.assurance import AssuranceCase, RecommendedAction


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
    """Produce a deterministic, evidence-bounded explanation.

    This is the M5 provider boundary: a hosted LLM can replace this function
    later, but it must preserve the same structured output and evidence IDs.
    """
    exposure = f"Rs {case.exposure_inr:,.0f}"
    violation = case.violation_type.value if case.violation_type else ""
    
    if violation == "DUPLICATE_COLLECTION":
        return GroundedExplanation(
            provider="grounded-deterministic-v1",
            summary=(
                "The same order resulted in more than one successful collection."
            ),
            root_cause=(
                "The original payment later completed after an automated retry had "
                "already captured successfully."
            ),
            why_flagged=(
                "Multiple successful captures were associated with the same financial intent."
            ),
            recommendation=(
                "Refund the duplicate collection."
            ),
            confidence=case.confidence,
            evidence_event_ids=case.evidence_event_ids,
        )
        
    if violation == "LATE_EVIDENCE":
        return GroundedExplanation(
            provider="grounded-deterministic-v1",
            summary="Required dispute evidence was submitted after the allowed deadline.",
            root_cause="The dispute workflow did not receive the required evidence within the permitted submission window.",
            why_flagged="The evidence submission timestamp exceeded the dispute deadline.",
            recommendation="Escalate for review.",
            confidence=case.confidence,
            evidence_event_ids=case.evidence_event_ids,
        )
        
    if violation == "REFUND_FAILURE":
        return GroundedExplanation(
            provider="grounded-deterministic-v1",
            summary="The refund was requested but the provider reported that the refund failed.",
            root_cause="The recovery action did not complete successfully at the provider.",
            why_flagged="The requested refund has no confirmed successful completion event.",
            recommendation="Retry or escalate the refund.",
            confidence=case.confidence,
            evidence_event_ids=case.evidence_event_ids,
        )
        
    if violation == "SETTLEMENT_VARIANCE":
        return GroundedExplanation(
            provider="grounded-deterministic-v1",
            summary="The settlement amount does not match the amount expected from the captured payment activity.",
            root_cause="The settlement reconciliation produced an unexplained amount difference.",
            why_flagged="The provider settlement amount differs from the reconstructed expected amount.",
            recommendation="Investigate settlement discrepancy.",
            confidence=case.confidence,
            evidence_event_ids=case.evidence_event_ids,
        )

    # Fallback for others
    action = case.recommended_action.value if case.recommended_action else "ESCALATE"
    return GroundedExplanation(
        provider="grounded-deterministic-v1",
        summary=case.violation_description or "Anomalous event sequence detected.",
        root_cause=f"The deterministic invariant for {violation if violation else 'anomalous behavior'} was breached.",
        why_flagged="The reconstructed state machine did not match the required invariants.",
        recommendation=f"Recommended action: {action}.",
        confidence=case.confidence,
        evidence_event_ids=case.evidence_event_ids,
    )
