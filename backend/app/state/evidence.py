"""
Evidence State Machine
----------------------
Reconstructs the "Evidence State" of an order from the EventStream.

Unlike the Financial State which deals in numbers (amounts, refunds),
the Evidence State deals in facts (delivery status, customer claims).
This state is used to detect Disputes with contradictory evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Any

from app.models.event import EventStream, EventType

@dataclass
class EvidenceState:
    order_id: str
    
    # What the customer claims happened (e.g. "PRODUCT_NOT_RECEIVED", "FRAUDULENT")
    dispute_claim: Optional[str] = None
    dispute_status: Optional[str] = None
    funds_withheld: bool = False
    
    # What the evidence says happened
    delivery_status: Optional[str] = None
    customer_communication: Optional[str] = None
    
    # Other potential fields extracted from metadata
    evidence_dict: dict[str, Any] = field(default_factory=dict)
    
    @property
    def has_dispute(self) -> bool:
        return self.dispute_claim is not None


class EvidenceStateMachine:
    """
    Scans the EventStream for DISPUTE and EVIDENCE events to reconstruct
    the factual state of an order.
    """
    
    def resolve(self, stream: EventStream) -> EvidenceState:
        state = EvidenceState(order_id=stream.order_id or "unknown")
        
        for event in stream.events:
            if event.event_type == EventType.DISPUTE_CREATED:
                reason = event.metadata.get("reason")
                if reason:
                    # Normalize claim reason (upper case)
                    state.dispute_claim = reason.upper()
                    
            elif event.event_type == EventType.DISPUTE_EVIDENCE_SUBMITTED:
                evidence = event.metadata.get("evidence", {})
                
                # Update specific strong-typed evidence
                if "delivery_status" in evidence:
                    state.delivery_status = evidence["delivery_status"].upper()
                if "customer_communication" in evidence:
                    state.customer_communication = evidence["customer_communication"].upper()
                    
                # Store all other raw evidence
                for k, v in evidence.items():
                    state.evidence_dict[k] = v
                    
            elif event.event_type == EventType.DISPUTE_CLOSED:
                status = event.metadata.get("status")
                if status:
                    state.dispute_status = status.lower()
                if "funds_withheld" in event.metadata:
                    state.funds_withheld = bool(event.metadata["funds_withheld"])
                    
        return state
