from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from app.cases.assurance import AssuranceCase
from app.models.event import EventStream, EventType


from app.learning.features import OutcomeFeatures, extract_features
from app.learning.risk_model import KnownActionRiskModel
from app.learning.anomaly import UnknownPatternDetector


@dataclass
class OutcomeRecord:
    case_id: str
    features: OutcomeFeatures
    violation_type: str | None = None
    pattern_hash: str | None = None
    resolved: bool = False
    recommended_action: str | None = None
    human_approved_action: str | None = None
    actual_action: str | None = None
    final_status: str | None = None
    outcome_verified: bool = False
    
    source_type: str | None = None
    source_record_id: str | None = None
    verification_evidence_ids: list[str] | None = None
    model_version: str | None = None

    resolution_duration_seconds: float | None = None
    financial_exposure: float | None = None
    action_amount: float | None = None
    verified_amount_recovered: float | None = None
    remaining_exposure: float | None = None
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "violation_type": self.violation_type,
            "pattern_hash": self.pattern_hash,
            "features": self.features.to_dict(),
            "resolved": self.resolved,
            "recommended_action": self.recommended_action,
            "human_approved_action": self.human_approved_action,
            "actual_action": self.actual_action,
            "final_status": self.final_status,
            "outcome_verified": self.outcome_verified,
            "source_type": self.source_type,
            "source_record_id": self.source_record_id,
            "verification_evidence_ids": self.verification_evidence_ids,
            "model_version": self.model_version,
            "resolution_duration_seconds": self.resolution_duration_seconds,
            "financial_exposure": self.financial_exposure,
            "action_amount": self.action_amount,
            "verified_amount_recovered": self.verified_amount_recovered,
            "remaining_exposure": self.remaining_exposure,
            "recorded_at": self.recorded_at.isoformat(),
        }

import hashlib
import json

def get_canonical_hash(stream: EventStream) -> tuple[list[str], str]:
    """
    Extracts the canonical sequence of event types and returns
    (sequence, sha256_hash).
    """
    seq = [e.event_type for e in stream.events]
    seq_str = json.dumps(seq)
    h = hashlib.sha256(seq_str.encode("utf-8")).hexdigest()
    return seq, h


class OutcomeMemory:
    """Outcome store with advisory ML risk model and pattern detector."""

    def __init__(self, repository=None) -> None:
        self.repository = repository
        self.risk_model = KnownActionRiskModel()
        self.anomaly_detector = UnknownPatternDetector()

    def record(self, case: AssuranceCase, stream: EventStream) -> OutcomeRecord:
        record = OutcomeRecord(
            case_id=case.case_id,
            features=extract_features(case, stream),
            violation_type=case.violation_type.value if case.violation_type else None,
            pattern_hash=case.pattern_hash,
            recommended_action=case.recommended_action.value if case.recommended_action else None,
            final_status=case.status.value if case.status else None,
            financial_exposure=case.financial_exposure,
            recorded_at=datetime.now(timezone.utc)
        )
        if self.repository:
            self.repository.save_memory_record(record)
        return record

    def mark_resolved(self, case: AssuranceCase, actual_action: str) -> OutcomeRecord | None:
        if not self.repository:
            return None
        # We need to get the existing record to update it
        records = self.repository.get_memory_records()
        record = next((r for r in records if r.case_id == case.case_id), None)
        if record is None:
            return None
            
        record.resolved = case.status == "ASSURED" or case.status == "FALSE_POSITIVE"
        record.actual_action = actual_action
        record.human_approved_action = actual_action if not case.requires_human_approval else (case.recommended_action.value if case.recommended_action else None)
        record.final_status = case.status.value if case.status else None
        record.outcome_verified = case.outcome_verified
        record.violation_type = case.violation_type.value if case.violation_type else None
        record.pattern_hash = case.pattern_hash
        
        # Enforce Provenance
        if case.outcome_verified:
            if not case.outcome_details:
                raise ValueError("Cannot verify outcome without outcome_details acting as cryptographic proof.")
            if "mode" not in case.outcome_details or "verification" not in case.outcome_details:
                raise ValueError("Outcome proof is missing strict provenance fields (mode, verification).")
            # If it's a verified recovery, require proof of recovery (e.g. exposure_details relevant_event_ids)
            if not case.exposure_details or not case.exposure_details.get("relevant_event_ids"):
                raise ValueError("Outcome proof is missing causal evidence linkage (relevant_event_ids).")

            record.source_type = case.outcome_details.get("mode")
            record.source_record_id = case.outcome_details.get("refund_id") or case.outcome_details.get("payment_id")
            record.verification_evidence_ids = case.exposure_details.get("relevant_event_ids", [])
        
        if case.resolved_at:
            duration = (case.resolved_at - case.created_at).total_seconds()
            record.resolution_duration_seconds = duration
            
        if case.outcome_details:
            eliminated = case.outcome_details.get("financial_exposure_eliminated", 0)
            record.action_amount = eliminated
            record.verified_amount_recovered = eliminated if case.outcome_verified else 0
            record.remaining_exposure = max(0, case.financial_exposure - record.verified_amount_recovered)
        
        self.repository.save_memory_record(record)
        
        # Learn verified pattern if classified
        from app.cases.assurance import PatternStatus
        if case.status.value == "ASSURED" and case.outcome_verified and case.pattern_status == PatternStatus.CLASSIFIED and case.pattern_hash:
            if case.human_classification and "violation_type" in case.human_classification:
                # We need the canonical stream here...
                # Actually, stream is not passed to mark_resolved.
                # Let's fetch it from repository
                stream = self.repository.get_stream(case.order_id) if case.order_id else None
                if stream:
                    seq, h = get_canonical_hash(stream)
                    self.repository.save_pattern_record(
                        pattern_hash=case.pattern_hash,
                        canonical_sequence=seq,
                        classified_violation=case.human_classification["violation_type"]
                    )
        
        return record

    def risk_for(self, case: AssuranceCase, stream: EventStream) -> dict:
        features = extract_features(case, stream)
        
        records = self.repository.get_memory_records() if self.repository else []
        
        # 1. Historical Exact Matches (for transparency)
        similar = [
            record for record in records
            if record.features.workflow == features.workflow
            and record.features.violation_type == features.violation_type
            and record.case_id != case.case_id
        ]
        failures = sum(not record.resolved for record in similar)
        historical_rate = failures / len(similar) if similar else 0.0
        
        # 2. ML Risk Model & External Signal
        deterministic_status = "NO_VIOLATION" if case.violation_type is None else str(case.violation_type)
        eval_result = self.risk_model.evaluate_risk(features, deterministic_status)
        
        assurance_risk = eval_result["assurance_risk"]
        if assurance_risk == -1.0:
            # Fallback if model missing
            from app.cases.assurance import ViolationType
            if case.violation_type == ViolationType.NO_VIOLATION:
                risk = 0.0
            else:
                risk = None
        else:
            risk = assurance_risk
            
        external_signal = eval_result["external_behavior_signal"]
        is_anomaly = self.anomaly_detector.is_anomaly(features)
            
        recommendation = "delay retry" if features.has_timeout and features.agent_action_count else "require human approval"
        if is_anomaly:
            recommendation = "flag for investigation (anomaly)"
            
        return {
            "risk_score": round(risk, 3) if risk is not None else None,
            "external_behavior_signal": round(external_signal, 3) if external_signal is not None else None,
            "historical_similar_cases": len(similar),
            "historical_unresolved_rate": round(historical_rate, 3),
            "is_anomaly": is_anomaly,
            "recommendation": recommendation,
            "reason": _risk_reason(features, recommendation, is_anomaly),
            "features": features.to_dict(),
        }


def _risk_reason(features: OutcomeFeatures, recommendation: str, is_anomaly: bool) -> str:
    if is_anomaly:
        return "The pattern of events does not match standard historical signatures. Requires investigation."
    if recommendation == "delay retry":
        return "A timeout and autonomous agent action occurred before the final payment outcome was known."
    return f"{features.violation_type} has {features.capture_count} captured outcomes across {features.event_count} recorded events."
