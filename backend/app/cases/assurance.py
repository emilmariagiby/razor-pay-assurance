"""
Assurance Case
--------------
The structured output of Assurance's investigation of a financial anomaly.

An AssuranceCase is the complete picture:
  - What action triggered this investigation
  - What state was expected
  - What state was actually observed
  - Why it happened (causal chain)
  - How much money is at risk (exposure)
  - What should be done (recommendation)
  - Whether a human needs to approve it
  - What happened after (outcome verification)

This is the object that powers the UI, the API, and the demo.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Any


# ---------------------------------------------------------------------------
# Case Enumerations
# ---------------------------------------------------------------------------

class ViolationType(str, Enum):
    DUPLICATE_COLLECTION           = "DUPLICATE_COLLECTION"
    PAYMENT_AMOUNT_MISMATCH        = "PAYMENT_AMOUNT_MISMATCH"
    UNCERTAIN_PAYMENT_CAPTURED     = "UNCERTAIN_PAYMENT_CAPTURED"
    REFUND_EXCEEDS_CAPTURED        = "REFUND_EXCEEDS_CAPTURED"
    REFUND_REVERSAL                = "REFUND_REVERSAL"
    REFUND_NOT_COMPLETED           = "REFUND_NOT_COMPLETED"
    DUPLICATE_REFUND               = "DUPLICATE_REFUND"
    SETTLEMENT_VARIANCE            = "SETTLEMENT_VARIANCE"
    SETTLEMENT_UNEXPLAINED         = "SETTLEMENT_UNEXPLAINED"
    DISPUTE_EVIDENCE_CONTRADICTION = "DISPUTE_EVIDENCE_CONTRADICTION"
    DISPUTE_MISSING_EVIDENCE       = "DISPUTE_MISSING_EVIDENCE"
    DISPUTE_ALREADY_REFUNDED       = "DISPUTE_ALREADY_REFUNDED"
    DISPUTE_DEADLINE_RISK          = "DISPUTE_DEADLINE_RISK"
    AUTOMATED_DISPUTE_CONTESTED    = "AUTOMATED_DISPUTE_CONTESTED"

    # New additions
    COLLECTION_AFTER_CANCELLATION= "COLLECTION_AFTER_CANCELLATION"
    AMOUNT_MISMATCH              = "AMOUNT_MISMATCH"
    CONFLICTING_AGENT_ACTION     = "CONFLICTING_AGENT_ACTION"
    REFUND_SLA_BREACH            = "REFUND_SLA_BREACH"
    REFUND_FAILURE               = "REFUND_FAILURE"
    REFUND_WITHOUT_CAPTURE       = "REFUND_WITHOUT_CAPTURE"
    UNEXPECTED_AGENT_REFUND      = "UNEXPECTED_AGENT_REFUND"
    MISSING_SETTLEMENT           = "MISSING_SETTLEMENT"
    SETTLEMENT_AMOUNT_MISMATCH   = "SETTLEMENT_AMOUNT_MISMATCH"
    UNEXPLAINED_ADJUSTMENT       = "UNEXPLAINED_ADJUSTMENT"
    CROSS_CYCLE_DISCREPANCY      = "CROSS_CYCLE_DISCREPANCY"
    CONTESTED_RESOLUTION         = "CONTESTED_RESOLUTION"
    NO_VIOLATION                 = "NO_VIOLATION"
    LATE_EVIDENCE                = "LATE_EVIDENCE"
    FUNDS_WITHHELD_INCORRECTLY   = "FUNDS_WITHHELD_INCORRECTLY"
    MISSING_CHARGEBACK_DEDUCTION = "MISSING_CHARGEBACK_DEDUCTION"
    CONCURRENT_DISPUTE_REFUND    = "CONCURRENT_DISPUTE_REFUND"


class PatternStatus(str, Enum):
    KNOWN       = "KNOWN"        # From 45 deterministic scenarios
    UNKNOWN     = "UNKNOWN"      # Custom case not triggering deterministic violations
    CLASSIFIED  = "CLASSIFIED"   # Human classified
    MATCHED     = "MATCHED"      # Recognized from verified Pattern Memory


class AssuranceCaseStatus(str, Enum):
    OPEN          = "OPEN"           # Detected, awaiting investigation
    INVESTIGATING = "INVESTIGATING"  # Under active review
    PENDING       = "PENDING"        # Waiting on human approval
    RESOLVING     = "RESOLVING"      # Corrective action in progress
    ASSURED       = "ASSURED"        # Resolved and verified
    FALSE_POSITIVE = "FALSE_POSITIVE" # Investigated and found to be benign


class RecommendedAction(str, Enum):
    REFUND_DUPLICATE  = "REFUND_DUPLICATE"
    CANCEL_REFUND     = "CANCEL_REFUND"
    CONTEST_DISPUTE   = "CONTEST_DISPUTE"
    ACCEPT_DISPUTE    = "ACCEPT_DISPUTE"
    ESCALATE          = "ESCALATE"
    MONITOR           = "MONITOR"
    NO_ACTION         = "NO_ACTION"


# ---------------------------------------------------------------------------
# Causal Step (serialisable version for the case object)
# ---------------------------------------------------------------------------

@dataclass
class CaseTimelineStep:
    timestamp:   datetime
    event_type:  str
    description: str
    payment_id:  Optional[str] = None
    amount_inr:  Optional[float] = None


# ---------------------------------------------------------------------------
# Assurance Case
# ---------------------------------------------------------------------------

@dataclass
class AssuranceCase:
    """
    The complete investigation record for a single financial anomaly.

    One violation → one Assurance Case.
    Each case can power: the dashboard card, the detail view, the evidence panel,
    and the corrective action workflow.
    """

    # Identity
    case_id:     str = field(default_factory=lambda: f"A-{uuid.uuid4().hex[:6].upper()}")
    created_at:  datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # What module triggered this
    workflow:    str = "retry"   # retry | refund | settlement | dispute

    # The violation
    pattern_status:       PatternStatus = PatternStatus.KNOWN
    violation_type:       Optional[ViolationType] = None
    violation_description: str = ""
    severity:             str = "HIGH"    # CRITICAL | HIGH | MEDIUM | LOW
    pattern_hash:         Optional[str] = None
    human_classification: Optional[dict] = None

    # Financial scope
    order_id:    Optional[str] = None
    merchant_id: Optional[str] = None

    # Expected vs Observed state
    expected_state: dict = field(default_factory=dict)
    observed_state: dict = field(default_factory=dict)

    # Financial exposure (paise)
    financial_exposure: int = 0
    exposure_details: dict = field(default_factory=dict)

    @property
    def exposure_inr(self) -> float:
        return (self.financial_exposure or 0) / 100

    # Confidence score from the assurance engine [0, 1]
    confidence: float = 0.0

    # Human-readable causal chain
    causal_summary:    str = ""
    causal_chain:      list[CaseTimelineStep] = field(default_factory=list)

    # Evidence: event IDs that support the violation claim
    evidence_event_ids: list[str] = field(default_factory=list)

    # Recommendation
    recommended_action:    Optional[RecommendedAction] = None
    recommendation_detail: str = ""
    requires_human_approval: bool = True

    # Status tracking
    status: AssuranceCaseStatus = AssuranceCaseStatus.OPEN
    resolved_at: Optional[datetime] = None
    resolution_note: str = ""

    # After resolution: was the outcome actually verified?
    outcome_verified: bool = False
    outcome_details:  dict = field(default_factory=dict)

    # Provenance Tracking (Priority 3)
    provenance_source: str = ""
    provenance_record_id: str = ""
    provenance_evidence_ids: list[str] = field(default_factory=list)
    provenance_model_version: str = ""

    def approve_recommendation(self, note: str = "") -> None:
        """Human approves the recommended action — moves to RESOLVING."""
        self.status = AssuranceCaseStatus.RESOLVING
        self.resolution_note = note

    def verify_state_match(self, expected: dict, observed: dict) -> bool:
        """
        Hard invariant: EXPECTED OUTCOME == OBSERVED OUTCOME
        This method must be called to reconstruct the state and verify.
        """
        self.expected_state = expected
        self.observed_state = observed
        
        # Determine if they match semantically.
        # This will be expanded by the ExposureCalculator in Priority 2,
        # but for now, we do a basic check on the exposure amount or keys.
        # Ensure we have actual state to compare
        if not expected or not observed:
            return False
            
        # For a basic exact match of the dictionaries:
        return expected == observed

    def attempt_verification(
        self, 
        expected: dict, 
        observed: dict, 
        outcome: dict | None = None,
        provenance_source: str = "",
        provenance_record_id: str = "",
        provenance_evidence_ids: list[str] | None = None,
        provenance_model_version: str = ""
    ) -> bool:
        """
        Attempts to mark this case as ASSURED by formally comparing
        the expected financial state against the observed provider state.
        Never blindly accepts outcome_verified=True.
        """
        if self.verify_state_match(expected, observed):
            self.status = AssuranceCaseStatus.ASSURED
            self.resolved_at = datetime.now(timezone.utc)
            self.outcome_verified = True
            
            # Lock in provenance upon successful verification
            self.provenance_source = provenance_source
            self.provenance_record_id = provenance_record_id
            self.provenance_evidence_ids = provenance_evidence_ids or []
            self.provenance_model_version = provenance_model_version
            
            if outcome:
                self.outcome_details = outcome
            return True
        else:
            self.status = AssuranceCaseStatus.PENDING
            self.outcome_verified = False
            if outcome:
                self.outcome_details = outcome
            return False

    def to_dict(self) -> dict:
        """Serialise to a plain dict (for the API / JSON output)."""
        return {
            "case_id":              self.case_id,
            "created_at":          self.created_at.isoformat(),
            "workflow":            self.workflow,
            "pattern_status":      self.pattern_status.value if self.pattern_status else None,
            "violation_type":      self.violation_type.value if self.violation_type else None,
            "violation_description": self.violation_description,
            "severity":            self.severity,
            "pattern_hash":        self.pattern_hash,
            "human_classification": self.human_classification,
            "order_id":            self.order_id,
            "merchant_id":         self.merchant_id,
            "expected_state":      self.expected_state,
            "observed_state":      self.observed_state,
            "financial_exposure":  self.financial_exposure,
            "exposure_details":    self.exposure_details,
            "exposure_inr":        self.exposure_inr,
            "confidence":          self.confidence,
            "causal_summary":      self.causal_summary,
            "causal_chain":        [
                {
                    "timestamp":   step.timestamp.isoformat(),
                    "event_type":  step.event_type,
                    "description": step.description,
                    "payment_id":  step.payment_id,
                    "amount_inr":  step.amount_inr,
                }
                for step in self.causal_chain
            ],
            "evidence_event_ids":    self.evidence_event_ids,
            "recommended_action":    self.recommended_action.value if self.recommended_action else None,
            "recommendation_detail": self.recommendation_detail,
            "requires_human_approval": self.requires_human_approval,
            "status":               self.status.value,
            "resolved_at":          self.resolved_at.isoformat() if self.resolved_at else None,
            "resolution_note":      self.resolution_note,
            "outcome_verified":     self.outcome_verified,
            "outcome_details":      self.outcome_details,
            "provenance_source":    self.provenance_source,
            "provenance_record_id": self.provenance_record_id,
            "provenance_evidence_ids": self.provenance_evidence_ids,
            "provenance_model_version": self.provenance_model_version,
        }

    def __repr__(self) -> str:
        return (
            f"AssuranceCase({self.case_id}, "
            f"{self.violation_type.value if self.violation_type else 'UNKNOWN'}, "
            f"₹{self.exposure_inr:,.0f}, "
            f"confidence={self.confidence:.0%}, "
            f"status={self.status.value})"
        )
