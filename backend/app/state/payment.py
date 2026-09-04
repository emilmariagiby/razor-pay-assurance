"""
Payment State Machine
---------------------
Given a stream of events for a single payment_id, derive its current state.

Critical design decision:
    TIMEOUT ≠ FAILED

A timeout means "we don't know yet." The payment may still succeed.
This distinction is the entire reason duplicate collection happens —
agents treat TIMEOUT as FAILED and retry, but the original succeeds later.

We model this explicitly with UNCERTAIN state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from app.models.event import EventStream, EventType, EventSource, FinancialEvent


# ---------------------------------------------------------------------------
# Payment States
# ---------------------------------------------------------------------------

class PaymentState(str, Enum):
    """
    All possible states a payment can be in.

    The key insight: UNCERTAIN is a real state.
    A payment that timed out is not FAILED — it's UNCERTAIN.
    """
    CREATED    = "CREATED"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED   = "CAPTURED"
    FAILED     = "FAILED"
    TIMEOUT    = "TIMEOUT"
    UNCERTAIN  = "UNCERTAIN"    # After timeout — outcome not yet known
    CANCELLED  = "CANCELLED"
    REFUNDED   = "REFUNDED"     # Fully refunded
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


# Which states represent a successful collection of funds (even if later refunded)
SUCCESSFUL_STATES = {
    PaymentState.CAPTURED,
    PaymentState.REFUNDED,
    PaymentState.PARTIALLY_REFUNDED,
}

# Which states are terminal — payment cannot transition further
TERMINAL_STATES = {
    PaymentState.CAPTURED,
    PaymentState.FAILED,
    PaymentState.CANCELLED,
    PaymentState.REFUNDED,
}

# Which states are "uncertain" — we don't yet know the outcome
UNCERTAIN_STATES = {
    PaymentState.TIMEOUT,
    PaymentState.UNCERTAIN,
}


# ---------------------------------------------------------------------------
# State Transition Log
# ---------------------------------------------------------------------------

@dataclass
class StateTransition:
    from_state:   Optional[PaymentState]
    to_state:     PaymentState
    triggered_by: FinancialEvent
    timestamp:    datetime

    def __repr__(self) -> str:
        frm = self.from_state.value if self.from_state else "None"
        return f"{frm} → {self.to_state.value} @ {self.timestamp.strftime('%H:%M:%S')}"


# ---------------------------------------------------------------------------
# Resolved Payment — the full picture of a single payment
# ---------------------------------------------------------------------------

@dataclass
class ResolvedPayment:
    payment_id:  str
    state:       PaymentState
    amount:      Optional[int]           # paise
    currency:    str = "INR"
    transitions: list[StateTransition] = field(default_factory=list)
    events:      list[FinancialEvent]  = field(default_factory=list)
    # Was this payment initiated by an autonomous agent?
    agent_initiated: bool = False
    # Which event caused this payment to be created? (e.g., a retry)
    caused_by_event_id: Optional[str] = None

    @property
    def is_successful(self) -> bool:
        return self.state in SUCCESSFUL_STATES

    @property
    def is_uncertain(self) -> bool:
        return self.state in UNCERTAIN_STATES

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def amount_inr(self) -> Optional[float]:
        return self.amount / 100 if self.amount else None

    def __repr__(self) -> str:
        amt = f" ₹{self.amount_inr:,.0f}" if self.amount else ""
        return f"Payment({self.payment_id}{amt}, state={self.state.value})"


# ---------------------------------------------------------------------------
# Payment State Machine
# ---------------------------------------------------------------------------

class PaymentStateMachine:
    """
    Derives the current state of a payment from its raw event stream.

    Usage:
        machine = PaymentStateMachine()
        resolved = machine.resolve(payment_id, stream)
    """

    # Valid transitions: (from_state | None) → to_state
    # None means "no prior state" (initial transition)
    TRANSITIONS: dict[tuple[Optional[PaymentState], PaymentState], bool] = {
        (None,                        PaymentState.CREATED):    True,
        (PaymentState.CREATED,        PaymentState.AUTHORIZED): True,
        (PaymentState.CREATED,        PaymentState.FAILED):     True,
        (PaymentState.CREATED,        PaymentState.TIMEOUT):    True,
        (PaymentState.CREATED,        PaymentState.CANCELLED):  True,
        (PaymentState.AUTHORIZED,     PaymentState.CAPTURED):   True,
        (PaymentState.AUTHORIZED,     PaymentState.FAILED):     True,
        # TIMEOUT → UNCERTAIN is the key transition
        (PaymentState.TIMEOUT,        PaymentState.UNCERTAIN):  True,
        # UNCERTAIN can still resolve — this is the late authorization case
        (PaymentState.UNCERTAIN,      PaymentState.AUTHORIZED): True,
        (PaymentState.UNCERTAIN,      PaymentState.CAPTURED):   True,
        (PaymentState.UNCERTAIN,      PaymentState.FAILED):     True,
        (PaymentState.CAPTURED,       PaymentState.REFUNDED):   True,
        (PaymentState.CAPTURED,       PaymentState.PARTIALLY_REFUNDED): True,
        (PaymentState.PARTIALLY_REFUNDED, PaymentState.REFUNDED): True,
    }

    # Map from event type to the state it drives a payment into
    EVENT_TO_STATE: dict[str, PaymentState] = {
        EventType.PAYMENT_CREATED:    PaymentState.CREATED,
        EventType.PAYMENT_AUTHORIZED: PaymentState.AUTHORIZED,
        EventType.PAYMENT_CAPTURED:   PaymentState.CAPTURED,
        EventType.PAYMENT_FAILED:     PaymentState.FAILED,
        EventType.PAYMENT_TIMEOUT:    PaymentState.TIMEOUT,
        EventType.PAYMENT_CANCELLED:  PaymentState.CANCELLED,
        EventType.REFUND_COMPLETED:   PaymentState.REFUNDED,
    }

    def resolve(self, payment_id: str, stream: EventStream) -> ResolvedPayment:
        """
        Walk through all events for this payment_id in chronological order
        and derive its current state via valid transitions.
        """
        events = stream.for_payment(payment_id)
        if not events:
            raise ValueError(f"No events found for payment {payment_id}")

        # Determine amount from the first event that has one
        amount = next((e.amount for e in events if e.amount is not None), None)
        currency = next((e.currency for e in events), "INR")

        # Was this payment agent-initiated?
        agent_initiated = any(
            e.event_type == EventType.AGENT_RETRY_INITIATED
            or (e.source == EventSource.AGENT and e.event_type == EventType.PAYMENT_CREATED)
            for e in events
        )

        # Caused by which event?
        create_event = next(
            (e for e in events if e.event_type == EventType.PAYMENT_CREATED), None
        )
        caused_by = create_event.caused_by_event_id if create_event else None

        current_state: Optional[PaymentState] = None
        transitions: list[StateTransition] = []

        for event in events:
            # Determine what state this event drives us into
            new_state = self._event_to_state(current_state, event)
            if new_state is None:
                continue  # Event doesn't change payment state

            if new_state == current_state:
                continue  # No change

            transitions.append(StateTransition(
                from_state=current_state,
                to_state=new_state,
                triggered_by=event,
                timestamp=event.timestamp,
            ))
            current_state = new_state

            # A timeout immediately makes the payment outcome uncertain. Keep
            # this transition attached to the timeout event so a later event
            # remains the true cause of authorization or capture.
            if current_state == PaymentState.TIMEOUT:
                transitions.append(StateTransition(
                    from_state=PaymentState.TIMEOUT,
                    to_state=PaymentState.UNCERTAIN,
                    triggered_by=event,
                    timestamp=event.timestamp,
                ))
                current_state = PaymentState.UNCERTAIN

        if current_state is None:
            raise ValueError(f"Could not derive state for payment {payment_id}")

        return ResolvedPayment(
            payment_id=payment_id,
            state=current_state,
            amount=amount,
            currency=currency,
            transitions=transitions,
            events=events,
            agent_initiated=agent_initiated,
            caused_by_event_id=caused_by,
        )

    def _event_to_state(
        self,
        current: Optional[PaymentState],
        event: FinancialEvent,
    ) -> Optional[PaymentState]:
        """Map an event to a target state, applying special transition rules."""

        raw_target = self.EVENT_TO_STATE.get(event.event_type)
        if raw_target is None:
            return None

        # Validate the transition
        if (current, raw_target) in self.TRANSITIONS:
            return raw_target

        # Allow UNCERTAIN → AUTHORIZED/CAPTURED (late authorization)
        if current == PaymentState.UNCERTAIN and raw_target in (
            PaymentState.AUTHORIZED,
            PaymentState.CAPTURED,
            PaymentState.FAILED,
        ):
            return raw_target

        return None  # Invalid transition, ignore the event
