"""
Settlement State Machine
------------------------
Reconstructs the Settlement State of an order from the EventStream.

This differs from standard payment state because settlement involves
transaction dates vs settlement dates, fees, and adjustments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.models.event import EventStream, EventType

@dataclass
class ResolvedSettlement:
    settlement_id: str
    
    # Financials
    amount: int = 0  # paise
    fees: int = 0
    adjustments: int = 0
    
    # Is it processed?
    is_processed: bool = False
    
    @property
    def amount_inr(self) -> float:
        return self.amount / 100

@dataclass
class SettlementState:
    order_id: str
    settlements: dict[str, ResolvedSettlement] = field(default_factory=dict)
    
    @property
    def total_settled(self) -> int:
        return sum(s.amount for s in self.settlements.values() if s.is_processed)
        
    @property
    def total_fees(self) -> int:
        return sum(s.fees for s in self.settlements.values())
        
    @property
    def total_adjustments(self) -> int:
        return sum(s.adjustments for s in self.settlements.values())


class SettlementStateMachine:
    """
    Derives the Settlement State from the EventStream.
    """
    
    def resolve(self, stream: EventStream) -> SettlementState:
        state = SettlementState(order_id=stream.order_id or "unknown")
        
        for event in stream.events:
            sid = event.settlement_id
            if not sid:
                continue
                
            if sid not in state.settlements:
                state.settlements[sid] = ResolvedSettlement(settlement_id=sid)
                
            settlement = state.settlements[sid]
            
            if event.event_type == EventType.SETTLEMENT_CREATED:
                pass # Initialized above
                
            elif event.event_type == EventType.SETTLEMENT_PROCESSED:
                settlement.is_processed = True
                if event.amount is not None:
                    settlement.amount = event.amount
                fees = event.metadata.get("fees")
                if fees is not None:
                    settlement.fees += fees
                    
            elif event.event_type == EventType.SETTLEMENT_ADJUSTED:
                if event.amount is not None:
                    # Adjustments are added to the adjustment total (e.g. -80000 for chargeback)
                    settlement.adjustments += event.amount
                    
        return state
