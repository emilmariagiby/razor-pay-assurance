import pytest
from datetime import datetime, timezone, timedelta
from app.cases.exposure import ExposureCalculator, ExposureResult
from app.cases.assurance import AssuranceCase, ViolationType
from app.models.event import EventStream, FinancialEvent, EventType, EventSource

def _create_event(event_type: EventType, amount: int, refund_id: str = None) -> FinancialEvent:
    return FinancialEvent(
        event_id=f"evt_{datetime.now().timestamp()}",
        event_type=event_type,
        timestamp=datetime.now(timezone.utc),
        source=EventSource.RAZORPAY,
        amount=amount,
        refund_id=refund_id
    )

def test_duplicate_collection():
    calc = ExposureCalculator()
    case = AssuranceCase(violation_type=ViolationType.DUPLICATE_COLLECTION)
    stream = EventStream()
    stream.add(_create_event(EventType.PAYMENT_CAPTURED, 25000))
    stream.add(_create_event(EventType.PAYMENT_CAPTURED, 25000))
    
    result = calc.calculate(case, stream)
    assert result.gross_exposure == 25000
    assert result.remaining_exposure == 25000

def test_full_refund():
    calc = ExposureCalculator()
    case = AssuranceCase(violation_type=ViolationType.DUPLICATE_COLLECTION, financial_exposure=25000)
    stream = EventStream()
    stream.add(_create_event(EventType.PAYMENT_CAPTURED, 25000))
    stream.add(_create_event(EventType.PAYMENT_CAPTURED, 25000))
    stream.add(_create_event(EventType.REFUND_REQUESTED, 25000, "ref_1"))
    stream.add(_create_event(EventType.REFUND_COMPLETED, 25000, "ref_1"))
    
    result = calc.calculate(case, stream)
    assert result.gross_exposure == 25000
    assert result.recovery_initiated == 25000
    assert result.verified_recovery == 25000
    assert result.remaining_exposure == 0

def test_partial_refund():
    calc = ExposureCalculator()
    case = AssuranceCase(violation_type=ViolationType.DUPLICATE_COLLECTION)
    stream = EventStream()
    stream.add(_create_event(EventType.PAYMENT_CAPTURED, 25000))
    stream.add(_create_event(EventType.PAYMENT_CAPTURED, 25000))
    stream.add(_create_event(EventType.REFUND_COMPLETED, 10000, "ref_1"))
    
    result = calc.calculate(case, stream)
    assert result.gross_exposure == 25000
    assert result.verified_recovery == 10000
    assert result.remaining_exposure == 15000

def test_over_refund():
    calc = ExposureCalculator()
    case = AssuranceCase(violation_type=ViolationType.REFUND_EXCEEDS_CAPTURED)
    stream = EventStream()
    stream.add(_create_event(EventType.PAYMENT_CAPTURED, 25000))
    stream.add(_create_event(EventType.REFUND_COMPLETED, 30000, "ref_1"))
    
    result = calc.calculate(case, stream)
    assert result.gross_exposure == 5000
    assert result.expected_amount == 25000
    assert result.actual_amount == 30000

def test_missing_capture():
    calc = ExposureCalculator()
    case = AssuranceCase(violation_type=ViolationType.MISSING_SETTLEMENT)
    stream = EventStream()
    stream.add(_create_event(EventType.PAYMENT_CAPTURED, 25000))
    
    result = calc.calculate(case, stream)
    assert result.gross_exposure == 25000
    assert result.actual_amount == 0

def test_multiple_refunds():
    calc = ExposureCalculator()
    case = AssuranceCase(violation_type=ViolationType.DUPLICATE_COLLECTION)
    stream = EventStream()
    stream.add(_create_event(EventType.PAYMENT_CAPTURED, 25000))
    stream.add(_create_event(EventType.PAYMENT_CAPTURED, 25000))
    stream.add(_create_event(EventType.REFUND_COMPLETED, 10000, "ref_1"))
    stream.add(_create_event(EventType.REFUND_COMPLETED, 15000, "ref_2"))
    
    result = calc.calculate(case, stream)
    assert result.gross_exposure == 25000
    assert result.verified_recovery == 25000
    assert result.remaining_exposure == 0

def test_duplicate_refund_event():
    calc = ExposureCalculator()
    case = AssuranceCase(violation_type=ViolationType.DUPLICATE_COLLECTION)
    stream = EventStream()
    stream.add(_create_event(EventType.PAYMENT_CAPTURED, 25000))
    stream.add(_create_event(EventType.PAYMENT_CAPTURED, 25000))
    # Two completions for the exact same refund ID (idempotency check)
    stream.add(_create_event(EventType.REFUND_COMPLETED, 25000, "ref_1"))
    stream.add(_create_event(EventType.REFUND_COMPLETED, 25000, "ref_1"))
    
    result = calc.calculate(case, stream)
    assert result.gross_exposure == 25000
    assert result.verified_recovery == 25000 # Should not double count!
    assert result.remaining_exposure == 0

def test_failed_refund():
    calc = ExposureCalculator()
    case = AssuranceCase(violation_type=ViolationType.DUPLICATE_COLLECTION)
    stream = EventStream()
    stream.add(_create_event(EventType.PAYMENT_CAPTURED, 25000))
    stream.add(_create_event(EventType.PAYMENT_CAPTURED, 25000))
    stream.add(_create_event(EventType.REFUND_REQUESTED, 25000, "ref_1"))
    stream.add(_create_event(EventType.REFUND_FAILED, 25000, "ref_1")) # Failed
    
    result = calc.calculate(case, stream)
    assert result.gross_exposure == 25000
    assert result.verified_recovery == 0
    assert result.remaining_exposure == 25000

def test_no_exposure():
    calc = ExposureCalculator()
    case = AssuranceCase(violation_type=ViolationType.NO_VIOLATION)
    stream = EventStream()
    stream.add(_create_event(EventType.PAYMENT_CAPTURED, 25000))
    
    result = calc.calculate(case, stream)
    assert result.gross_exposure == 0

def test_amount_scaling():
    calc = ExposureCalculator()
    case = AssuranceCase(violation_type=ViolationType.DUPLICATE_COLLECTION)
    stream = EventStream()
    stream.add(_create_event(EventType.PAYMENT_CAPTURED, 25000123))
    stream.add(_create_event(EventType.PAYMENT_CAPTURED, 25000123))
    
    result = calc.calculate(case, stream)
    assert result.gross_exposure == 25000123
