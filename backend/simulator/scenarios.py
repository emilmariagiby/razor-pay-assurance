"""
Scenario Simulator
------------------
Generates synthetic but realistic financial event streams for testing.

Each scenario has a known ground truth so we can verify that Assurance
classifies it correctly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.models.event import (
    FinancialEvent,
    EventStream,
    EventType,
    EventSource,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_TIME = datetime(2026, 8, 27, 10, 0, 0, tzinfo=timezone.utc)

def _t(seconds: int) -> datetime:
    """Return a timestamp offset from base time."""
    return _BASE_TIME + timedelta(seconds=seconds)

def _make_event(
    event_type:   EventType,
    timestamp:    datetime,
    source:       EventSource,
    order_id:     str,
    payment_id:   Optional[str] = None,
    refund_id:    Optional[str] = None,
    settlement_id: Optional[str] = None,
    dispute_id:   Optional[str] = None,
    amount:       Optional[int] = None,   # paise
    caused_by:    Optional[str] = None,
    merchant_id:  str = "merch_001",
    customer_id:  str = "cust_001",
    metadata:     dict | None = None,
) -> FinancialEvent:
    return FinancialEvent(
        event_type=event_type,
        timestamp=timestamp,
        source=source,
        merchant_id=merchant_id,
        customer_id=customer_id,
        order_id=order_id,
        payment_id=payment_id,
        refund_id=refund_id,
        settlement_id=settlement_id,
        dispute_id=dispute_id,
        amount=amount,
        caused_by_event_id=caused_by,
        metadata=metadata or {},
    )

# ---------------------------------------------------------------------------
# Ground-Truth Metadata
# ---------------------------------------------------------------------------

GROUND_TRUTH = {
    # Retry (5)
    "normal_payment":          {"expects_violation": False, "violation_type": None},
    "retry_success":           {"expects_violation": False, "violation_type": None},
    "late_auth_duplicate":     {"expects_violation": True,  "violation_type": "DUPLICATE_COLLECTION"},
    "two_legitimate_orders":   {"expects_violation": False, "violation_type": None},
    "multiple_retry_anomaly":  {"expects_violation": True,  "violation_type": "DUPLICATE_COLLECTION"},

    # Refund (5)
    "refund_clean":            {"expects_violation": False, "violation_type": None},
    "refund_reversal":         {"expects_violation": True,  "violation_type": "REFUND_REVERSAL"},
    "over_refund":             {"expects_violation": True,  "violation_type": "REFUND_EXCEEDS_CAPTURED"},
    "duplicate_refund":        {"expects_violation": True,  "violation_type": "DUPLICATE_REFUND"},
    "partial_refund":          {"expects_violation": False, "violation_type": None},

    # Settlement (5)
    "settlement_clean":               {"expects_violation": False, "violation_type": None},
    "settlement_variance":            {"expects_violation": True,  "violation_type": "SETTLEMENT_VARIANCE"},
    "settlement_variance_explained":  {"expects_violation": False, "violation_type": None},
    "settlement_previous_refund":     {"expects_violation": False, "violation_type": None},
    "settlement_chargeback":          {"expects_violation": False, "violation_type": None},

    # Dispute (5)
    "dispute_strong_evidence": {"expects_violation": False, "violation_type": None},
    "dispute_missing_evidence":{"expects_violation": True,  "violation_type": "DISPUTE_MISSING_EVIDENCE"},
    "dispute_contradiction":   {"expects_violation": True,  "violation_type": "DISPUTE_EVIDENCE_CONTRADICTION"},
    "dispute_already_refunded":{"expects_violation": True,  "violation_type": "DISPUTE_ALREADY_REFUNDED"},
    "dispute_deadline_risk":   {"expects_violation": True,  "violation_type": "DISPUTE_DEADLINE_RISK"},

    # Retry (New)
    "retry_after_captured": {"expects_violation": True, "violation_type": "DUPLICATE_COLLECTION"},
    "retry_after_cancellation": {"expects_violation": True, "violation_type": "COLLECTION_AFTER_CANCELLATION"},
    "retry_amount_mismatch": {"expects_violation": True, "violation_type": "PAYMENT_AMOUNT_MISMATCH"},
    "uncertain_payment_captured": {"expects_violation": True, "violation_type": "UNCERTAIN_PAYMENT_CAPTURED"},
    "agent_retry_downstream_anomaly": {"expects_violation": True, "violation_type": "CONFLICTING_AGENT_ACTION"},

    # Refund (New)
    "refund_stuck_pending": {"expects_violation": True, "violation_type": "REFUND_SLA_BREACH"},
    "refund_failed": {"expects_violation": True, "violation_type": "REFUND_FAILURE"},
    "refund_against_invalid_payment": {"expects_violation": True, "violation_type": "REFUND_WITHOUT_CAPTURE"},
    "agent_initiated_unexpected_refund": {"expects_violation": True, "violation_type": "UNEXPECTED_AGENT_REFUND"},

    # Settlement (New)
    "settlement_missing_funds": {"expects_violation": True, "violation_type": "MISSING_SETTLEMENT"},
    "settlement_amount_inconsistent": {"expects_violation": True, "violation_type": "SETTLEMENT_AMOUNT_MISMATCH"},
    "unexplained_settlement_adjustment": {"expects_violation": True, "violation_type": "UNEXPLAINED_ADJUSTMENT"},
    "cross_cycle_adjustment": {"expects_violation": True, "violation_type": "CROSS_CYCLE_DISCREPANCY"},

    # Dispute (New)
    "automated_dispute_contested": {"expects_violation": True, "violation_type": "AUTOMATED_DISPUTE_CONTESTED"},
    "evidence_after_deadline": {"expects_violation": True, "violation_type": "LATE_EVIDENCE"},
    "dispute_outcome_inconsistent": {"expects_violation": True, "violation_type": "FUNDS_WITHHELD_INCORRECTLY"},
    "dispute_plus_settlement_interaction": {"expects_violation": True, "violation_type": "MISSING_CHARGEBACK_DEDUCTION"},

    # Cross-Workflow (New)
    "duplicate_collection_to_assured": {"expects_violation": True, "violation_type": "UNCERTAIN_PAYMENT_CAPTURED"},
    "duplicate_collection_reversal": {"expects_violation": True, "violation_type": "REFUND_REVERSAL"},
    "refund_plus_active_dispute": {"expects_violation": True, "violation_type": "CONCURRENT_DISPUTE_REFUND"},
    "capture_settlement_variance": {"expects_violation": True, "violation_type": "SETTLEMENT_UNEXPLAINED"},
    "agent_action_bad_outcome": {"expects_violation": False, "violation_type": None},
    "dispute_settlement_discrepancy": {"expects_violation": False, "violation_type": None},
    "cross_cycle_anomaly": {"expects_violation": True, "violation_type": "CROSS_CYCLE_DISCREPANCY"},
    "refund_completed_dispute_created": {"expects_violation": True, "violation_type": "DISPUTE_ALREADY_REFUNDED"},

}

# ---------------------------------------------------------------------------
# RETRY WORKFLOW
# ---------------------------------------------------------------------------

def normal_payment() -> EventStream:
    stream = EventStream(order_id="ord_r1")
    stream.add(_make_event(EventType.PAYMENT_CREATED,    _t(0), EventSource.GATEWAY, "ord_r1", payment_id="pay_r1", amount=2500000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2), EventSource.BANK,    "ord_r1", payment_id="pay_r1", amount=2500000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED,   _t(3), EventSource.GATEWAY, "ord_r1", payment_id="pay_r1", amount=2500000))
    return stream

def retry_success() -> EventStream:
    stream = EventStream(order_id="ord_r2")
    e_a = _make_event(EventType.PAYMENT_CREATED, _t(0),  EventSource.GATEWAY, "ord_r2", payment_id="pay_r2a", amount=5000000)
    e_t = _make_event(EventType.PAYMENT_TIMEOUT, _t(5),  EventSource.GATEWAY, "ord_r2", payment_id="pay_r2a")
    stream.add(e_a)
    stream.add(e_t)
    e_ret = _make_event(EventType.AGENT_RETRY_INITIATED, _t(30), EventSource.AGENT, "ord_r2", payment_id="pay_r2a", caused_by=e_t.event_id)
    stream.add(e_ret)
    stream.add(_make_event(EventType.PAYMENT_CREATED,    _t(31), EventSource.AGENT, "ord_r2", payment_id="pay_r2b", amount=5000000, caused_by=e_ret.event_id))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(33), EventSource.BANK,  "ord_r2", payment_id="pay_r2b", amount=5000000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED,   _t(34), EventSource.GATEWAY, "ord_r2", payment_id="pay_r2b", amount=5000000))
    stream.add(_make_event(EventType.PAYMENT_FAILED,     _t(120), EventSource.BANK, "ord_r2", payment_id="pay_r2a"))
    return stream

def late_auth_duplicate() -> EventStream:
    stream = EventStream(order_id="ord_r3")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(1),  EventSource.GATEWAY, "ord_r3", payment_id="pay_A", amount=2500000))
    e_t = _make_event(EventType.PAYMENT_TIMEOUT, _t(6),  EventSource.GATEWAY, "ord_r3", payment_id="pay_A")
    stream.add(e_t)
    e_retry = _make_event(EventType.AGENT_RETRY_INITIATED, _t(31), EventSource.AGENT, "ord_r3", payment_id="pay_A", caused_by=e_t.event_id)
    stream.add(e_retry)
    stream.add(_make_event(EventType.PAYMENT_CREATED,    _t(34), EventSource.AGENT,   "ord_r3", payment_id="pay_B", amount=2500000, caused_by=e_retry.event_id))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(36), EventSource.BANK,    "ord_r3", payment_id="pay_B", amount=2500000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED,   _t(37), EventSource.GATEWAY, "ord_r3", payment_id="pay_B", amount=2500000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(252), EventSource.BANK,   "ord_r3", payment_id="pay_A", amount=2500000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED,   _t(253), EventSource.GATEWAY, "ord_r3", payment_id="pay_A", amount=2500000))
    return stream

def two_legitimate_orders() -> EventStream:
    stream = EventStream(order_id="ord_r4")
    stream.add(_make_event(EventType.PAYMENT_CREATED,    _t(0), EventSource.GATEWAY, "ord_r4", payment_id="pay_r4a", amount=1000000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2), EventSource.BANK,    "ord_r4", payment_id="pay_r4a", amount=1000000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED,   _t(3), EventSource.GATEWAY, "ord_r4", payment_id="pay_r4a", amount=1000000))
    return stream

def multiple_retry_anomaly() -> EventStream:
    stream = EventStream(order_id="ord_r5")
    e_a = _make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_r5", payment_id="pay_r5a", amount=100000)
    e_t = _make_event(EventType.PAYMENT_TIMEOUT, _t(5), EventSource.GATEWAY, "ord_r5", payment_id="pay_r5a")
    stream.add(e_a)
    stream.add(e_t)
    # Retry 1
    e_r1 = _make_event(EventType.AGENT_RETRY_INITIATED, _t(10), EventSource.AGENT, "ord_r5", payment_id="pay_r5a", caused_by=e_t.event_id)
    stream.add(e_r1)
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(11), EventSource.AGENT, "ord_r5", payment_id="pay_r5b", amount=100000, caused_by=e_r1.event_id))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(12), EventSource.BANK, "ord_r5", payment_id="pay_r5b", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(13), EventSource.GATEWAY, "ord_r5", payment_id="pay_r5b", amount=100000))
    # Retry 2 (buggy agent retries again despite success)
    e_r2 = _make_event(EventType.AGENT_RETRY_INITIATED, _t(15), EventSource.AGENT, "ord_r5", payment_id="pay_r5a", caused_by=e_t.event_id)
    stream.add(e_r2)
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(16), EventSource.AGENT, "ord_r5", payment_id="pay_r5c", amount=100000, caused_by=e_r2.event_id))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(17), EventSource.BANK, "ord_r5", payment_id="pay_r5c", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(18), EventSource.GATEWAY, "ord_r5", payment_id="pay_r5c", amount=100000))
    return stream

# ---------------------------------------------------------------------------
# REFUND WORKFLOW
# ---------------------------------------------------------------------------

def refund_clean() -> EventStream:
    stream = EventStream(order_id="ord_f1")
    stream.add(_make_event(EventType.PAYMENT_CREATED,    _t(0),  EventSource.GATEWAY, "ord_f1", payment_id="pay_f1", amount=3000000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2),  EventSource.BANK,    "ord_f1", payment_id="pay_f1", amount=3000000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED,   _t(3),  EventSource.GATEWAY, "ord_f1", payment_id="pay_f1", amount=3000000))
    stream.add(_make_event(EventType.REFUND_REQUESTED,   _t(60), EventSource.MERCHANT, "ord_f1", payment_id="pay_f1", refund_id="ref_f1", amount=3000000))
    stream.add(_make_event(EventType.REFUND_PROCESSED,   _t(62), EventSource.GATEWAY,  "ord_f1", payment_id="pay_f1", refund_id="ref_f1", amount=3000000))
    stream.add(_make_event(EventType.REFUND_COMPLETED,   _t(120),EventSource.BANK,     "ord_f1", payment_id="pay_f1", refund_id="ref_f1", amount=3000000))
    return stream

def refund_reversal() -> EventStream:
    stream = EventStream(order_id="ord_f2")
    stream.add(_make_event(EventType.PAYMENT_CREATED,    _t(0),  EventSource.GATEWAY, "ord_f2", payment_id="pay_f2", amount=1000000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2),  EventSource.BANK,    "ord_f2", payment_id="pay_f2", amount=1000000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED,   _t(3),  EventSource.GATEWAY, "ord_f2", payment_id="pay_f2", amount=1000000))
    stream.add(_make_event(EventType.REFUND_REQUESTED,   _t(60), EventSource.AGENT,   "ord_f2", payment_id="pay_f2", refund_id="ref_f2", amount=1000000))
    stream.add(_make_event(EventType.REFUND_PROCESSED,   _t(62), EventSource.GATEWAY, "ord_f2", payment_id="pay_f2", refund_id="ref_f2", amount=1000000))
    stream.add(_make_event(EventType.REFUND_COMPLETED,   _t(90), EventSource.BANK,    "ord_f2", payment_id="pay_f2", refund_id="ref_f2", amount=1000000))
    stream.add(_make_event(EventType.REFUND_REVERSED,    _t(200), EventSource.BANK,   "ord_f2", payment_id="pay_f2", refund_id="ref_f2", amount=1000000))
    return stream

def over_refund() -> EventStream:
    stream = EventStream(order_id="ord_f3")
    stream.add(_make_event(EventType.PAYMENT_CREATED,    _t(0),  EventSource.GATEWAY, "ord_f3", payment_id="pay_f3", amount=500000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2),  EventSource.BANK,    "ord_f3", payment_id="pay_f3", amount=500000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED,   _t(3),  EventSource.GATEWAY, "ord_f3", payment_id="pay_f3", amount=500000))
    stream.add(_make_event(EventType.REFUND_REQUESTED,   _t(60), EventSource.AGENT,   "ord_f3", payment_id="pay_f3", refund_id="ref_f3", amount=1000000))
    stream.add(_make_event(EventType.REFUND_PROCESSED,   _t(62), EventSource.GATEWAY, "ord_f3", payment_id="pay_f3", refund_id="ref_f3", amount=1000000))
    return stream

def duplicate_refund() -> EventStream:
    stream = EventStream(order_id="ord_f4")
    stream.add(_make_event(EventType.PAYMENT_CREATED,    _t(0),  EventSource.GATEWAY, "ord_f4", payment_id="pay_f4", amount=1000000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2),  EventSource.BANK,    "ord_f4", payment_id="pay_f4", amount=1000000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED,   _t(3),  EventSource.GATEWAY, "ord_f4", payment_id="pay_f4", amount=1000000))
    # Refund 1
    stream.add(_make_event(EventType.REFUND_REQUESTED,   _t(60), EventSource.AGENT,   "ord_f4", payment_id="pay_f4", refund_id="ref_f4a", amount=1000000))
    stream.add(_make_event(EventType.REFUND_COMPLETED,   _t(62), EventSource.BANK,    "ord_f4", payment_id="pay_f4", refund_id="ref_f4a", amount=1000000))
    # Refund 2
    stream.add(_make_event(EventType.REFUND_REQUESTED,   _t(70), EventSource.MERCHANT,"ord_f4", payment_id="pay_f4", refund_id="ref_f4b", amount=1000000))
    stream.add(_make_event(EventType.REFUND_COMPLETED,   _t(72), EventSource.BANK,    "ord_f4", payment_id="pay_f4", refund_id="ref_f4b", amount=1000000))
    return stream

def partial_refund() -> EventStream:
    stream = EventStream(order_id="ord_f5")
    stream.add(_make_event(EventType.PAYMENT_CREATED,    _t(0),  EventSource.GATEWAY, "ord_f5", payment_id="pay_f5", amount=1000000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2),  EventSource.BANK,    "ord_f5", payment_id="pay_f5", amount=1000000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED,   _t(3),  EventSource.GATEWAY, "ord_f5", payment_id="pay_f5", amount=1000000))
    stream.add(_make_event(EventType.REFUND_REQUESTED,   _t(60), EventSource.CUSTOMER,"ord_f5", payment_id="pay_f5", refund_id="ref_f5", amount=400000))
    stream.add(_make_event(EventType.REFUND_COMPLETED,   _t(62), EventSource.BANK,    "ord_f5", payment_id="pay_f5", refund_id="ref_f5", amount=400000))
    return stream

# ---------------------------------------------------------------------------
# SETTLEMENT WORKFLOW
# ---------------------------------------------------------------------------

def settlement_clean() -> EventStream:
    stream = EventStream(order_id="ord_s1")
    stream.add(_make_event(EventType.PAYMENT_CREATED,      _t(0),   EventSource.GATEWAY,  "ord_s1", payment_id="pay_s1", amount=1000000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED,   _t(2),   EventSource.BANK,     "ord_s1", payment_id="pay_s1", amount=1000000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED,     _t(3),   EventSource.GATEWAY,  "ord_s1", payment_id="pay_s1", amount=1000000))
    stream.add(_make_event(EventType.REFUND_REQUESTED,     _t(60),  EventSource.MERCHANT, "ord_s1", payment_id="pay_s1", refund_id="ref_s1", amount=200000))
    stream.add(_make_event(EventType.REFUND_COMPLETED,     _t(120), EventSource.BANK,     "ord_s1", payment_id="pay_s1", refund_id="ref_s1", amount=200000))
    stream.add(_make_event(EventType.SETTLEMENT_CREATED,   _t(172800), EventSource.RAZORPAY, "ord_s1", settlement_id="set_s1"))
    stream.add(_make_event(EventType.SETTLEMENT_PROCESSED, _t(259200), EventSource.RAZORPAY, "ord_s1", settlement_id="set_s1", amount=780000, metadata={"fees": 20000}))  
    return stream

def settlement_variance() -> EventStream:
    stream = EventStream(order_id="ord_s2")
    stream.add(_make_event(EventType.PAYMENT_CREATED,      _t(0),   EventSource.GATEWAY,  "ord_s2", payment_id="pay_s2", amount=1000000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED,   _t(2),   EventSource.BANK,     "ord_s2", payment_id="pay_s2", amount=1000000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED,     _t(3),   EventSource.GATEWAY,  "ord_s2", payment_id="pay_s2", amount=1000000))
    stream.add(_make_event(EventType.SETTLEMENT_CREATED,   _t(172800), EventSource.RAZORPAY, "ord_s2", settlement_id="set_s2"))
    stream.add(_make_event(EventType.SETTLEMENT_PROCESSED, _t(259200), EventSource.RAZORPAY, "ord_s2", settlement_id="set_s2", amount=900000, metadata={"fees": 20000}))  
    return stream

def settlement_variance_explained() -> EventStream:
    stream = EventStream(order_id="ord_s3")
    stream.add(_make_event(EventType.PAYMENT_CREATED,      _t(0),   EventSource.GATEWAY,  "ord_s3", payment_id="pay_s3", amount=1000000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED,   _t(2),   EventSource.BANK,     "ord_s3", payment_id="pay_s3", amount=1000000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED,     _t(3),   EventSource.GATEWAY,  "ord_s3", payment_id="pay_s3", amount=1000000))
    stream.add(_make_event(EventType.SETTLEMENT_ADJUSTED,  _t(100), EventSource.RAZORPAY, "ord_s3", settlement_id="set_s3", amount=-80000, metadata={"reason": "adjustment"}))
    stream.add(_make_event(EventType.SETTLEMENT_CREATED,   _t(172800), EventSource.RAZORPAY, "ord_s3", settlement_id="set_s3"))
    stream.add(_make_event(EventType.SETTLEMENT_PROCESSED, _t(259200), EventSource.RAZORPAY, "ord_s3", settlement_id="set_s3", amount=900000, metadata={"fees": 20000}))  
    return stream

def settlement_previous_refund() -> EventStream:
    stream = EventStream(order_id="ord_s4")
    stream.add(_make_event(EventType.PAYMENT_CREATED,      _t(0),   EventSource.GATEWAY,  "ord_s4", payment_id="pay_s4", amount=1000000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED,   _t(2),   EventSource.BANK,     "ord_s4", payment_id="pay_s4", amount=1000000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED,     _t(3),   EventSource.GATEWAY,  "ord_s4", payment_id="pay_s4", amount=1000000))
    stream.add(_make_event(EventType.SETTLEMENT_CREATED,   _t(172800), EventSource.RAZORPAY, "ord_s4", settlement_id="set_s4"))
    stream.add(_make_event(EventType.SETTLEMENT_PROCESSED, _t(259200), EventSource.RAZORPAY, "ord_s4", settlement_id="set_s4", amount=980000, metadata={"fees": 20000}))  
    return stream

def settlement_chargeback() -> EventStream:
    stream = EventStream(order_id="ord_s5")
    stream.add(_make_event(EventType.PAYMENT_CREATED,      _t(0),   EventSource.GATEWAY,  "ord_s5", payment_id="pay_s5", amount=1000000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED,   _t(2),   EventSource.BANK,     "ord_s5", payment_id="pay_s5", amount=1000000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED,     _t(3),   EventSource.GATEWAY,  "ord_s5", payment_id="pay_s5", amount=1000000))
    stream.add(_make_event(EventType.SETTLEMENT_ADJUSTED,  _t(100), EventSource.RAZORPAY, "ord_s5", settlement_id="set_s5", amount=-1000000, metadata={"reason": "chargeback"}))
    stream.add(_make_event(EventType.SETTLEMENT_CREATED,   _t(172800), EventSource.RAZORPAY, "ord_s5", settlement_id="set_s5"))
    stream.add(_make_event(EventType.SETTLEMENT_PROCESSED, _t(259200), EventSource.RAZORPAY, "ord_s5", settlement_id="set_s5", amount=-20000, metadata={"fees": 20000}))  
    return stream

# ---------------------------------------------------------------------------
# DISPUTE WORKFLOW
# ---------------------------------------------------------------------------

def dispute_strong_evidence() -> EventStream:
    stream = EventStream(order_id="ord_d1")
    stream.add(_make_event(EventType.PAYMENT_CREATED,    _t(0),  EventSource.GATEWAY, "ord_d1", payment_id="pay_d1", amount=750000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2),  EventSource.BANK,    "ord_d1", payment_id="pay_d1", amount=750000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED,   _t(3),  EventSource.GATEWAY, "ord_d1", payment_id="pay_d1", amount=750000))
    stream.add(_make_event(EventType.DISPUTE_CREATED,    _t(3600), EventSource.BANK,  "ord_d1", dispute_id="disp_d1", amount=750000,
                           metadata={"reason": "FRAUDULENT"}))
    stream.add(_make_event(EventType.DISPUTE_EVIDENCE_SUBMITTED, _t(3700), EventSource.MERCHANT, "ord_d1", dispute_id="disp_d1",
                           metadata={"evidence": {"ip_match": True, "cvv_match": True, "address_match": True}}))
    return stream

def dispute_missing_evidence() -> EventStream:
    stream = EventStream(order_id="ord_d2")
    stream.add(_make_event(EventType.PAYMENT_CREATED,    _t(0),  EventSource.GATEWAY, "ord_d2", payment_id="pay_d2", amount=750000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2),  EventSource.BANK,    "ord_d2", payment_id="pay_d2", amount=750000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED,   _t(3),  EventSource.GATEWAY, "ord_d2", payment_id="pay_d2", amount=750000))
    stream.add(_make_event(EventType.DISPUTE_CREATED,    _t(3600), EventSource.BANK,  "ord_d2", dispute_id="disp_d2", amount=750000,
                           metadata={"reason": "PRODUCT_NOT_RECEIVED"}))
    # Missing delivery evidence
    stream.add(_make_event(EventType.DISPUTE_EVIDENCE_SUBMITTED, _t(3700), EventSource.MERCHANT, "ord_d2", dispute_id="disp_d2",
                           metadata={"evidence": {"customer_email": "hello@world.com"}})) 
    return stream

def dispute_contradiction() -> EventStream:
    stream = EventStream(order_id="ord_d3")
    stream.add(_make_event(EventType.PAYMENT_CREATED,    _t(0),  EventSource.GATEWAY, "ord_d3", payment_id="pay_d3", amount=750000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2),  EventSource.BANK,    "ord_d3", payment_id="pay_d3", amount=750000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED,   _t(3),  EventSource.GATEWAY, "ord_d3", payment_id="pay_d3", amount=750000))
    stream.add(_make_event(EventType.DISPUTE_CREATED,    _t(3600), EventSource.BANK,  "ord_d3", dispute_id="disp_d3", amount=750000,
                           metadata={"reason": "PRODUCT_NOT_RECEIVED"}))
    stream.add(_make_event(EventType.DISPUTE_EVIDENCE_SUBMITTED, _t(3700), EventSource.MERCHANT, "ord_d3", dispute_id="disp_d3",
                           metadata={
                               "evidence": {
                                   "delivery_status": "DELIVERED",
                                   "customer_communication": "RECEIVED",
                               }
                           }))
    return stream

def dispute_already_refunded() -> EventStream:
    stream = EventStream(order_id="ord_d4")
    stream.add(_make_event(EventType.PAYMENT_CREATED,    _t(0),  EventSource.GATEWAY, "ord_d4", payment_id="pay_d4", amount=750000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2),  EventSource.BANK,    "ord_d4", payment_id="pay_d4", amount=750000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED,   _t(3),  EventSource.GATEWAY, "ord_d4", payment_id="pay_d4", amount=750000))
    # Refunded!
    stream.add(_make_event(EventType.REFUND_REQUESTED,   _t(100), EventSource.MERCHANT, "ord_d4", payment_id="pay_d4", refund_id="ref_d4", amount=750000))
    stream.add(_make_event(EventType.REFUND_COMPLETED,   _t(102), EventSource.BANK,    "ord_d4", payment_id="pay_d4", refund_id="ref_d4", amount=750000))
    # Dispute created after refund
    stream.add(_make_event(EventType.DISPUTE_CREATED,    _t(3600), EventSource.BANK,  "ord_d4", dispute_id="disp_d4", amount=750000,
                           metadata={"reason": "DUPLICATE"}))
    return stream

def dispute_deadline_risk() -> EventStream:
    stream = EventStream(order_id="ord_d5")
    stream.add(_make_event(EventType.PAYMENT_CREATED,    _t(0),  EventSource.GATEWAY, "ord_d5", payment_id="pay_d5", amount=750000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2),  EventSource.BANK,    "ord_d5", payment_id="pay_d5", amount=750000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED,   _t(3),  EventSource.GATEWAY, "ord_d5", payment_id="pay_d5", amount=750000))
    # Created a long time ago, approaching deadline
    stream.add(_make_event(EventType.DISPUTE_CREATED,    _t(3600), EventSource.BANK,  "ord_d5", dispute_id="disp_d5", amount=750000,
                           metadata={"reason": "FRAUDULENT", "deadline": _t(3600 + 86400).isoformat()}))
    # Current time is near deadline, no evidence submitted
    return stream

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# NEW RETRY WORKFLOWS
# ---------------------------------------------------------------------------
def retry_after_captured() -> EventStream:
    stream = EventStream(order_id="ord_new1")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_new1", payment_id="pay_new1a", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2), EventSource.BANK, "ord_new1", payment_id="pay_new1a", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(3), EventSource.GATEWAY, "ord_new1", payment_id="pay_new1a", amount=100000))
    # Retry after success
    e_ret = _make_event(EventType.AGENT_RETRY_INITIATED, _t(10), EventSource.AGENT, "ord_new1", payment_id="pay_new1a")
    stream.add(e_ret)
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(11), EventSource.AGENT, "ord_new1", payment_id="pay_new1b", amount=100000, caused_by=e_ret.event_id))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(13), EventSource.BANK, "ord_new1", payment_id="pay_new1b", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(14), EventSource.GATEWAY, "ord_new1", payment_id="pay_new1b", amount=100000))
    return stream

def retry_after_cancellation() -> EventStream:
    stream = EventStream(order_id="ord_new2")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_new2", payment_id="pay_new2a", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CANCELLED, _t(2), EventSource.CUSTOMER, "ord_new2", payment_id="pay_new2a", amount=100000))
    # Agent retries anyway
    e_ret = _make_event(EventType.AGENT_RETRY_INITIATED, _t(10), EventSource.AGENT, "ord_new2", payment_id="pay_new2a")
    stream.add(e_ret)
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(11), EventSource.AGENT, "ord_new2", payment_id="pay_new2b", amount=100000, caused_by=e_ret.event_id))
    return stream

def retry_amount_mismatch() -> EventStream:
    stream = EventStream(order_id="ord_new3")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_new3", payment_id="pay_new3a", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_FAILED, _t(2), EventSource.BANK, "ord_new3", payment_id="pay_new3a", amount=100000))
    e_ret = _make_event(EventType.AGENT_RETRY_INITIATED, _t(10), EventSource.AGENT, "ord_new3", payment_id="pay_new3a")
    stream.add(e_ret)
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(11), EventSource.AGENT, "ord_new3", payment_id="pay_new3b", amount=200000, caused_by=e_ret.event_id))
    return stream

def uncertain_payment_captured() -> EventStream:
    stream = EventStream(order_id="ord_new4")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_new4", payment_id="pay_new4a", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_TIMEOUT, _t(2), EventSource.GATEWAY, "ord_new4", payment_id="pay_new4a"))
    # Captures days later
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(86400), EventSource.BANK, "ord_new4", payment_id="pay_new4a", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(86401), EventSource.GATEWAY, "ord_new4", payment_id="pay_new4a", amount=100000))
    return stream

def agent_retry_downstream_anomaly() -> EventStream:
    stream = EventStream(order_id="ord_new5")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_new5", payment_id="pay_new5a", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2), EventSource.BANK, "ord_new5", payment_id="pay_new5a", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(3), EventSource.GATEWAY, "ord_new5", payment_id="pay_new5a", amount=100000))
    stream.add(_make_event(EventType.REFUND_REQUESTED, _t(100), EventSource.MERCHANT, "ord_new5", payment_id="pay_new5a", refund_id="ref_new5", amount=100000))
    # Agent retries while refund is pending
    e_ret = _make_event(EventType.AGENT_RETRY_INITIATED, _t(105), EventSource.AGENT, "ord_new5", payment_id="pay_new5a")
    stream.add(e_ret)
    return stream

# ---------------------------------------------------------------------------
# NEW REFUND WORKFLOWS
# ---------------------------------------------------------------------------
def refund_stuck_pending() -> EventStream:
    stream = EventStream(order_id="ord_ref1")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_ref1", payment_id="pay_ref1", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2), EventSource.BANK, "ord_ref1", payment_id="pay_ref1", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(3), EventSource.GATEWAY, "ord_ref1", payment_id="pay_ref1", amount=100000))
    stream.add(_make_event(EventType.REFUND_REQUESTED, _t(100), EventSource.MERCHANT, "ord_ref1", payment_id="pay_ref1", refund_id="ref_ref1", amount=100000))
    # Advance time heavily to trigger SLA
    stream.add(_make_event(EventType.SETTLEMENT_CREATED, _t(100000), EventSource.RAZORPAY, "ord_ref1", settlement_id="set_1"))
    return stream

def refund_failed() -> EventStream:
    stream = EventStream(order_id="ord_ref2")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_ref2", payment_id="pay_ref2", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2), EventSource.BANK, "ord_ref2", payment_id="pay_ref2", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(3), EventSource.GATEWAY, "ord_ref2", payment_id="pay_ref2", amount=100000))
    stream.add(_make_event(EventType.REFUND_REQUESTED, _t(100), EventSource.MERCHANT, "ord_ref2", payment_id="pay_ref2", refund_id="ref_ref2", amount=100000))
    stream.add(_make_event(EventType.REFUND_FAILED, _t(102), EventSource.GATEWAY, "ord_ref2", payment_id="pay_ref2", refund_id="ref_ref2", amount=100000))
    return stream

def refund_against_invalid_payment() -> EventStream:
    stream = EventStream(order_id="ord_ref3")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_ref3", payment_id="pay_ref3", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_FAILED, _t(3), EventSource.GATEWAY, "ord_ref3", payment_id="pay_ref3", amount=100000))
    stream.add(_make_event(EventType.REFUND_REQUESTED, _t(100), EventSource.MERCHANT, "ord_ref3", payment_id="pay_ref3", refund_id="ref_ref3", amount=100000))
    stream.add(_make_event(EventType.REFUND_PROCESSED, _t(101), EventSource.GATEWAY, "ord_ref3", payment_id="pay_ref3", refund_id="ref_ref3", amount=100000))
    stream.add(_make_event(EventType.REFUND_COMPLETED, _t(102), EventSource.BANK, "ord_ref3", payment_id="pay_ref3", refund_id="ref_ref3", amount=100000))
    return stream

def agent_initiated_unexpected_refund() -> EventStream:
    stream = EventStream(order_id="ord_ref4")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_ref4", payment_id="pay_ref4", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2), EventSource.BANK, "ord_ref4", payment_id="pay_ref4", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(3), EventSource.GATEWAY, "ord_ref4", payment_id="pay_ref4", amount=100000))
    stream.add(_make_event(EventType.AGENT_REFUND_INITIATED, _t(100), EventSource.AGENT, "ord_ref4", payment_id="pay_ref4", refund_id="ref_ref4", amount=100000))
    return stream

# ---------------------------------------------------------------------------
# NEW SETTLEMENT WORKFLOWS
# ---------------------------------------------------------------------------
def settlement_missing_funds() -> EventStream:
    stream = EventStream(order_id="ord_set1")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_set1", payment_id="pay_set1", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2), EventSource.BANK, "ord_set1", payment_id="pay_set1", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(3), EventSource.GATEWAY, "ord_set1", payment_id="pay_set1", amount=100000))
    stream.add(_make_event(EventType.SETTLEMENT_CREATED, _t(100000), EventSource.RAZORPAY, "ord_set1", settlement_id="set_1", metadata={"settlement_expected": True}))
    return stream

def settlement_amount_inconsistent() -> EventStream:
    stream = EventStream(order_id="ord_set2")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_set2", payment_id="pay_set2", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2), EventSource.BANK, "ord_set2", payment_id="pay_set2", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(3), EventSource.GATEWAY, "ord_set2", payment_id="pay_set2", amount=100000))
    stream.add(_make_event(EventType.SETTLEMENT_CREATED, _t(100000), EventSource.RAZORPAY, "ord_set2", settlement_id="set_2", metadata={"settlement_expected": True}))
    stream.add(_make_event(EventType.SETTLEMENT_PROCESSED, _t(100001), EventSource.RAZORPAY, "ord_set2", settlement_id="set_2", amount=0, metadata={"fees": 0}))
    return stream

def unexplained_settlement_adjustment() -> EventStream:
    stream = EventStream(order_id="ord_set3")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_set3", payment_id="pay_set3", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2), EventSource.BANK, "ord_set3", payment_id="pay_set3", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(3), EventSource.GATEWAY, "ord_set3", payment_id="pay_set3", amount=100000))
    stream.add(_make_event(EventType.SETTLEMENT_ADJUSTED, _t(50000), EventSource.RAZORPAY, "ord_set3", settlement_id="set_3", amount=-20000))
    stream.add(_make_event(EventType.SETTLEMENT_CREATED, _t(100000), EventSource.RAZORPAY, "ord_set3", settlement_id="set_3"))
    stream.add(_make_event(EventType.SETTLEMENT_PROCESSED, _t(100001), EventSource.RAZORPAY, "ord_set3", settlement_id="set_3", amount=80000, metadata={"fees": 0}))
    return stream

def cross_cycle_adjustment() -> EventStream:
    stream = EventStream(order_id="ord_set4")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_set4", payment_id="pay_set4", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2), EventSource.BANK, "ord_set4", payment_id="pay_set4", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(3), EventSource.GATEWAY, "ord_set4", payment_id="pay_set4", amount=100000))
    stream.add(_make_event(EventType.SETTLEMENT_ADJUSTED, _t(50000), EventSource.RAZORPAY, "ord_set4", settlement_id="set_4", amount=-20000, metadata={"cross_cycle": True}))
    stream.add(_make_event(EventType.SETTLEMENT_CREATED, _t(100000), EventSource.RAZORPAY, "ord_set4", settlement_id="set_4"))
    stream.add(_make_event(EventType.SETTLEMENT_PROCESSED, _t(100001), EventSource.RAZORPAY, "ord_set4", settlement_id="set_4", amount=80000, metadata={"fees": 0}))
    return stream

# ---------------------------------------------------------------------------
# NEW DISPUTE WORKFLOWS
# ---------------------------------------------------------------------------
def automated_dispute_contested() -> EventStream:
    stream = EventStream(order_id="ord_disp1")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_disp1", payment_id="pay_disp1", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2), EventSource.BANK, "ord_disp1", payment_id="pay_disp1", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(3), EventSource.GATEWAY, "ord_disp1", payment_id="pay_disp1", amount=100000))
    stream.add(_make_event(EventType.DISPUTE_CREATED, _t(1000), EventSource.BANK, "ord_disp1", dispute_id="disp_1", amount=100000, metadata={"reason": "FRAUDULENT"}))
    stream.add(_make_event(EventType.AGENT_DISPUTE_INITIATED, _t(1005), EventSource.AGENT, "ord_disp1", dispute_id="disp_1"))
    stream.add(_make_event(EventType.DISPUTE_EVIDENCE_SUBMITTED, _t(1010), EventSource.MERCHANT, "ord_disp1", dispute_id="disp_1", metadata={"evidence": {"delivery_status": "DELIVERED"}}))
    return stream

def evidence_after_deadline() -> EventStream:
    stream = EventStream(order_id="ord_disp2")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_disp2", payment_id="pay_disp2", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2), EventSource.BANK, "ord_disp2", payment_id="pay_disp2", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(3), EventSource.GATEWAY, "ord_disp2", payment_id="pay_disp2", amount=100000))
    stream.add(_make_event(EventType.DISPUTE_CREATED, _t(1000), EventSource.BANK, "ord_disp2", dispute_id="disp_2", amount=100000, metadata={"reason": "FRAUDULENT"}))
    stream.add(_make_event(EventType.DISPUTE_EVIDENCE_SUBMITTED, _t(5000), EventSource.MERCHANT, "ord_disp2", dispute_id="disp_2", metadata={"is_late": True}))
    return stream

def dispute_outcome_inconsistent() -> EventStream:
    stream = EventStream(order_id="ord_disp3")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_disp3", payment_id="pay_disp3", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2), EventSource.BANK, "ord_disp3", payment_id="pay_disp3", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(3), EventSource.GATEWAY, "ord_disp3", payment_id="pay_disp3", amount=100000))
    stream.add(_make_event(EventType.DISPUTE_CREATED, _t(1000), EventSource.BANK, "ord_disp3", dispute_id="disp_3", amount=100000, metadata={"reason": "FRAUDULENT"}))
    stream.add(_make_event(EventType.DISPUTE_CLOSED, _t(5000), EventSource.BANK, "ord_disp3", dispute_id="disp_3", metadata={"status": "won", "funds_withheld": True}))
    return stream

def dispute_plus_settlement_interaction() -> EventStream:
    stream = EventStream(order_id="ord_disp4")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_disp4", payment_id="pay_disp4", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2), EventSource.BANK, "ord_disp4", payment_id="pay_disp4", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(3), EventSource.GATEWAY, "ord_disp4", payment_id="pay_disp4", amount=100000))
    stream.add(_make_event(EventType.DISPUTE_CREATED, _t(1000), EventSource.BANK, "ord_disp4", dispute_id="disp_4", amount=100000, metadata={"reason": "FRAUDULENT"}))
    stream.add(_make_event(EventType.DISPUTE_CLOSED, _t(5000), EventSource.BANK, "ord_disp4", dispute_id="disp_4", metadata={"status": "lost", "funds_withheld": False}))
    stream.add(_make_event(EventType.SETTLEMENT_CREATED, _t(100000), EventSource.RAZORPAY, "ord_disp4", settlement_id="set_disp4"))
    stream.add(_make_event(EventType.SETTLEMENT_PROCESSED, _t(100001), EventSource.RAZORPAY, "ord_disp4", settlement_id="set_disp4", amount=0, metadata={"fees": 0})) # No adjustment recorded!
    return stream

# ---------------------------------------------------------------------------
# NEW CROSS-WORKFLOW
# ---------------------------------------------------------------------------
def duplicate_collection_to_assured() -> EventStream:
    # Full flagship loop
    stream = EventStream(order_id="ord_cw1")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_cw1", payment_id="pay_cw1a", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_TIMEOUT, _t(2), EventSource.GATEWAY, "ord_cw1", payment_id="pay_cw1a"))
    e_ret = _make_event(EventType.AGENT_RETRY_INITIATED, _t(10), EventSource.AGENT, "ord_cw1", payment_id="pay_cw1a")
    stream.add(e_ret)
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(11), EventSource.AGENT, "ord_cw1", payment_id="pay_cw1b", amount=100000, caused_by=e_ret.event_id))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(11), EventSource.BANK, "ord_cw1", payment_id="pay_cw1b", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(12), EventSource.GATEWAY, "ord_cw1", payment_id="pay_cw1b", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(49), EventSource.BANK, "ord_cw1", payment_id="pay_cw1a", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(50), EventSource.GATEWAY, "ord_cw1", payment_id="pay_cw1a", amount=100000))
    # Corrective action applied
    stream.add(_make_event(EventType.REFUND_REQUESTED, _t(100), EventSource.ASSURANCE, "ord_cw1", payment_id="pay_cw1a", refund_id="ref_cw1", amount=100000))
    stream.add(_make_event(EventType.REFUND_COMPLETED, _t(105), EventSource.BANK, "ord_cw1", payment_id="pay_cw1a", refund_id="ref_cw1", amount=100000))
    return stream

def duplicate_collection_reversal() -> EventStream:
    stream = duplicate_collection_to_assured()
    stream.add(_make_event(EventType.REFUND_REVERSED, _t(200), EventSource.BANK, "ord_cw1", payment_id="pay_cw1a", refund_id="ref_cw1", amount=100000))
    return stream

def refund_plus_active_dispute() -> EventStream:
    stream = EventStream(order_id="ord_cw3")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_cw3", payment_id="pay_cw3", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2), EventSource.BANK, "ord_cw3", payment_id="pay_cw3", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(3), EventSource.GATEWAY, "ord_cw3", payment_id="pay_cw3", amount=100000))
    stream.add(_make_event(EventType.REFUND_REQUESTED, _t(100), EventSource.MERCHANT, "ord_cw3", payment_id="pay_cw3", refund_id="ref_cw3", amount=100000))
    stream.add(_make_event(EventType.DISPUTE_CREATED, _t(102), EventSource.BANK, "ord_cw3", dispute_id="disp_cw3", amount=100000, metadata={"reason": "FRAUDULENT"}))
    return stream

def capture_settlement_variance() -> EventStream:
    # A mix of capture success but missing settlement explicitly modeled as cross-workflow
    stream = EventStream(order_id="ord_cw4")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_cw4", payment_id="pay_cw4", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2), EventSource.BANK, "ord_cw4", payment_id="pay_cw4", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(3), EventSource.GATEWAY, "ord_cw4", payment_id="pay_cw4", amount=100000))
    stream.add(_make_event(EventType.SETTLEMENT_CREATED, _t(100000), EventSource.RAZORPAY, "ord_cw4", settlement_id="set_cw4", metadata={"settlement_expected": True}))
    stream.add(_make_event(EventType.SETTLEMENT_PROCESSED, _t(100001), EventSource.RAZORPAY, "ord_cw4", settlement_id="set_cw4", amount=10000, metadata={"fees": 0, "unexplained_variance": True}))
    return stream

def agent_action_bad_outcome() -> EventStream:
    stream = EventStream(order_id="ord_cw5")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_cw5", payment_id="pay_cw5", amount=100000))
    stream.add(_make_event(EventType.AGENT_RETRY_INITIATED, _t(2), EventSource.AGENT, "ord_cw5", payment_id="pay_cw5"))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2), EventSource.BANK, "ord_cw5", payment_id="pay_cw5", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(3), EventSource.GATEWAY, "ord_cw5", payment_id="pay_cw5", amount=100000))
    stream.add(_make_event(EventType.SETTLEMENT_ADJUSTED, _t(100), EventSource.RAZORPAY, "ord_cw5", settlement_id="set_cw5", amount=-100000, metadata={"reason": "chargeback"}))
    return stream

def dispute_settlement_discrepancy() -> EventStream:
    stream = EventStream(order_id="ord_cw6")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_cw6", payment_id="pay_cw6", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2), EventSource.BANK, "ord_cw6", payment_id="pay_cw6", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(3), EventSource.GATEWAY, "ord_cw6", payment_id="pay_cw6", amount=100000))
    stream.add(_make_event(EventType.DISPUTE_CREATED, _t(100), EventSource.BANK, "ord_cw6", dispute_id="disp_cw6", amount=100000, metadata={"reason": "FRAUDULENT"}))
    stream.add(_make_event(EventType.DISPUTE_CLOSED, _t(200), EventSource.BANK, "ord_cw6", dispute_id="disp_cw6", metadata={"status": "won", "funds_withheld": False}))
    stream.add(_make_event(EventType.SETTLEMENT_ADJUSTED, _t(300), EventSource.RAZORPAY, "ord_cw6", settlement_id="set_cw6", amount=-100000, metadata={"reason": "chargeback"}))
    return stream

def cross_cycle_anomaly() -> EventStream:
    stream = EventStream(order_id="ord_cw7")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_cw7", payment_id="pay_cw7", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(99999), EventSource.BANK, "ord_cw7", payment_id="pay_cw7", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(100000), EventSource.GATEWAY, "ord_cw7", payment_id="pay_cw7", amount=100000))
    stream.add(_make_event(EventType.SETTLEMENT_PROCESSED, _t(150000), EventSource.RAZORPAY, "ord_cw7", settlement_id="set_cw7", amount=100000))
    stream.add(_make_event(EventType.SETTLEMENT_ADJUSTED, _t(200000), EventSource.RAZORPAY, "ord_cw7", settlement_id="set_cw7", amount=-50000, metadata={"cross_cycle": True}))
    return stream

def refund_completed_dispute_created() -> EventStream:
    stream = EventStream(order_id="ord_cw8")
    stream.add(_make_event(EventType.PAYMENT_CREATED, _t(0), EventSource.GATEWAY, "ord_cw8", payment_id="pay_cw8", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_AUTHORIZED, _t(2), EventSource.BANK, "ord_cw8", payment_id="pay_cw8", amount=100000))
    stream.add(_make_event(EventType.PAYMENT_CAPTURED, _t(3), EventSource.GATEWAY, "ord_cw8", payment_id="pay_cw8", amount=100000))
    stream.add(_make_event(EventType.REFUND_REQUESTED, _t(100), EventSource.MERCHANT, "ord_cw8", payment_id="pay_cw8", refund_id="ref_cw8", amount=100000))
    stream.add(_make_event(EventType.REFUND_COMPLETED, _t(105), EventSource.BANK, "ord_cw8", payment_id="pay_cw8", refund_id="ref_cw8", amount=100000))
    stream.add(_make_event(EventType.DISPUTE_CREATED, _t(50000), EventSource.BANK, "ord_cw8", dispute_id="disp_cw8", amount=100000, metadata={"reason": "FRAUDULENT"}))
    return stream

SCENARIOS = {
    "normal_payment":                normal_payment,
    "retry_success":                 retry_success,
    "late_auth_duplicate":           late_auth_duplicate,
    "two_legitimate_orders":         two_legitimate_orders,
    "multiple_retry_anomaly":        multiple_retry_anomaly,
    "refund_clean":                  refund_clean,
    "refund_reversal":               refund_reversal,
    "over_refund":                   over_refund,
    "duplicate_refund":              duplicate_refund,
    "partial_refund":                partial_refund,
    "settlement_clean":              settlement_clean,
    "settlement_variance":           settlement_variance,
    "settlement_variance_explained": settlement_variance_explained,
    "settlement_previous_refund":    settlement_previous_refund,
    "settlement_chargeback":         settlement_chargeback,
    "dispute_strong_evidence":       dispute_strong_evidence,
    "dispute_missing_evidence":      dispute_missing_evidence,
    "dispute_contradiction":         dispute_contradiction,
    "dispute_already_refunded":      dispute_already_refunded,
    "dispute_deadline_risk":         dispute_deadline_risk,
    "retry_after_captured": retry_after_captured,
    "retry_after_cancellation": retry_after_cancellation,
    "retry_amount_mismatch": retry_amount_mismatch,
    "uncertain_payment_captured": uncertain_payment_captured,
    "agent_retry_downstream_anomaly": agent_retry_downstream_anomaly,
    "refund_stuck_pending": refund_stuck_pending,
    "refund_failed": refund_failed,
    "refund_against_invalid_payment": refund_against_invalid_payment,
    "agent_initiated_unexpected_refund": agent_initiated_unexpected_refund,
    "settlement_missing_funds": settlement_missing_funds,
    "settlement_amount_inconsistent": settlement_amount_inconsistent,
    "unexplained_settlement_adjustment": unexplained_settlement_adjustment,
    "cross_cycle_adjustment": cross_cycle_adjustment,
    "automated_dispute_contested": automated_dispute_contested,
    "evidence_after_deadline": evidence_after_deadline,
    "dispute_outcome_inconsistent": dispute_outcome_inconsistent,
    "dispute_plus_settlement_interaction": dispute_plus_settlement_interaction,
    "duplicate_collection_to_assured": duplicate_collection_to_assured,
    "duplicate_collection_reversal": duplicate_collection_reversal,
    "refund_plus_active_dispute": refund_plus_active_dispute,
    "capture_settlement_variance": capture_settlement_variance,
    "agent_action_bad_outcome": agent_action_bad_outcome,
    "dispute_settlement_discrepancy": dispute_settlement_discrepancy,
    "cross_cycle_anomaly": cross_cycle_anomaly,
    "refund_completed_dispute_created": refund_completed_dispute_created,

}

def get_scenario(name: str) -> EventStream:
    if name not in SCENARIOS:
        raise ValueError(f"Unknown scenario '{name}'.")
    return SCENARIOS[name]()

def all_scenarios() -> dict[str, EventStream]:
    return {name: fn() for name, fn in SCENARIOS.items()}
