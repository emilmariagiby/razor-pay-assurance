from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.cases.assurance import AssuranceCase
from app.models.event import EventStream, EventType


@dataclass(frozen=True)
class OutcomeFeatures:
    workflow: str
    violation_type: str
    severity: str
    event_count: int
    payment_count: int
    capture_count: int
    agent_action_count: int
    has_timeout: bool
    exposure: int
    unique_event_type_count: int
    sequence_length: int
    retry_count: int
    timeout_count: int
    cancellation_count: int
    refund_count: int
    settlement_count: int
    dispute_count: int
    has_retry: bool
    has_cancellation: bool
    has_refund: bool
    has_settlement: bool
    time_to_resolution_sec: Optional[float] = None
    has_reversal: bool = False
    has_dispute: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "OutcomeFeatures":
        defaults = {
            "unique_event_type_count": 0,
            "sequence_length": data.get("event_count", 0),
            "retry_count": 0,
            "timeout_count": 1 if data.get("has_timeout") else 0,
            "cancellation_count": 0,
            "refund_count": 0,
            "settlement_count": 0,
            "dispute_count": 1 if data.get("has_dispute") else 0,
            "has_retry": False,
            "has_cancellation": False,
            "has_refund": False,
            "has_settlement": False
        }
        for k, v in defaults.items():
            if k not in data:
                data[k] = v
        return cls(**data)

    def to_dict(self) -> dict:
        return {
            "workflow": self.workflow,
            "violation_type": self.violation_type,
            "severity": self.severity,
            "event_count": self.event_count,
            "payment_count": self.payment_count,
            "capture_count": self.capture_count,
            "agent_action_count": self.agent_action_count,
            "has_timeout": self.has_timeout,
            "exposure": self.exposure,
            "time_to_resolution_sec": self.time_to_resolution_sec,
            "has_reversal": self.has_reversal,
            "has_dispute": self.has_dispute,
            "unique_event_type_count": self.unique_event_type_count,
            "sequence_length": self.sequence_length,
            "retry_count": self.retry_count,
            "timeout_count": self.timeout_count,
            "cancellation_count": self.cancellation_count,
            "refund_count": self.refund_count,
            "settlement_count": self.settlement_count,
            "dispute_count": self.dispute_count,
            "has_retry": self.has_retry,
            "has_cancellation": self.has_cancellation,
            "has_refund": self.has_refund,
            "has_settlement": self.has_settlement,
        }

    def to_vector(self) -> list[float]:
        """
        Convert strictly pre-decision behavioral features to a numerical vector for ML models.
        Excludes target labels, outcomes, identifiers, and post-decision data.
        """
        return [
            float(self.event_count),
            float(self.sequence_length),
            float(self.unique_event_type_count),
            float(self.retry_count),
            float(self.timeout_count),
            float(self.cancellation_count),
            float(self.refund_count),
            float(self.settlement_count),
            float(self.dispute_count),
            float(self.agent_action_count),
            float(self.has_retry),
            float(self.has_timeout),
            float(self.has_cancellation),
            float(self.has_refund),
            float(self.has_settlement),
            float(self.has_dispute),
            float(self.has_reversal),
            float(self.exposure),
        ]


def extract_features(case: AssuranceCase, stream: EventStream) -> OutcomeFeatures:
    events = stream.events
    
    time_to_resolution = None
    if len(events) >= 2:
        diff = events[-1].timestamp - events[0].timestamp
        time_to_resolution = diff.total_seconds()
        
    # Behavioral extractions
    event_types = [e.event_type for e in events]
    unique_event_types = len(set(event_types))
    
    retry_count = sum(1 for e in events if e.event_type == EventType.AGENT_RETRY_INITIATED)
    timeout_count = sum(1 for e in events if e.event_type == EventType.PAYMENT_TIMEOUT)
    cancellation_count = sum(1 for e in events if e.event_type == EventType.PAYMENT_CANCELLED)
    refund_count = sum(1 for e in events if e.event_type == EventType.REFUND_REQUESTED)
    settlement_count = sum(1 for e in events if e.event_type == EventType.SETTLEMENT_PROCESSED)
    dispute_count = sum(1 for e in events if e.event_type == EventType.DISPUTE_CREATED)

    return OutcomeFeatures(
        workflow=case.workflow,
        violation_type=str(case.violation_type) if case.violation_type else "UNKNOWN",
        severity=case.severity,
        event_count=len(events),
        payment_count=len(stream.payment_ids),
        capture_count=sum(event.event_type == EventType.PAYMENT_CAPTURED for event in events),
        agent_action_count=sum(event.source == "agent" for event in events),
        has_timeout=timeout_count > 0,
        exposure=case.financial_exposure,
        time_to_resolution_sec=time_to_resolution,
        has_reversal=any("reversal" in str(e.event_type).lower() for e in events),
        has_dispute=dispute_count > 0,
        unique_event_type_count=unique_event_types,
        sequence_length=len(events),
        retry_count=retry_count,
        timeout_count=timeout_count,
        cancellation_count=cancellation_count,
        refund_count=refund_count,
        settlement_count=settlement_count,
        dispute_count=dispute_count,
        has_retry=retry_count > 0,
        has_cancellation=cancellation_count > 0,
        has_refund=refund_count > 0,
        has_settlement=settlement_count > 0,
    )
