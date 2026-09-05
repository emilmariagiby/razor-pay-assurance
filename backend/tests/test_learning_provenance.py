import pytest
from app.cases.assurance import AssuranceCase, AssuranceCaseStatus
from app.models.event import EventStream, FinancialEvent
from app.learning.memory import OutcomeMemory

def test_learning_rejected_without_assured_status():
    memory = OutcomeMemory()
    case = AssuranceCase(
        case_id="TEST-1",
        order_id="ord_test",
        status=AssuranceCaseStatus.RESOLVING,
        outcome_verified=True,
        provenance_source="test",
        provenance_record_id="evt_123",
        provenance_evidence_ids=["evt_123"]
    )
    stream = EventStream(order_id="ord_test", events=[])
    
    record = memory.record(case, stream)
    assert record is None, "Should reject if status != ASSURED"

def test_learning_rejected_without_verification():
    memory = OutcomeMemory()
    case = AssuranceCase(
        case_id="TEST-2",
        order_id="ord_test",
        status=AssuranceCaseStatus.ASSURED,
        outcome_verified=False,
        provenance_source="test",
        provenance_record_id="evt_123",
        provenance_evidence_ids=["evt_123"]
    )
    stream = EventStream(order_id="ord_test", events=[])
    
    record = memory.record(case, stream)
    assert record is None, "Should reject if outcome not verified"

def test_learning_rejected_without_provenance_source():
    memory = OutcomeMemory()
    case = AssuranceCase(
        case_id="TEST-3",
        order_id="ord_test",
        status=AssuranceCaseStatus.ASSURED,
        outcome_verified=True,
        provenance_source="",
        provenance_record_id="evt_123",
        provenance_evidence_ids=["evt_123"]
    )
    stream = EventStream(order_id="ord_test", events=[])
    
    record = memory.record(case, stream)
    assert record is None, "Should reject if provenance source is empty"

def test_learning_rejected_without_evidence_ids():
    memory = OutcomeMemory()
    case = AssuranceCase(
        case_id="TEST-4",
        order_id="ord_test",
        status=AssuranceCaseStatus.ASSURED,
        outcome_verified=True,
        provenance_source="test",
        provenance_record_id="evt_123",
        provenance_evidence_ids=[]
    )
    stream = EventStream(order_id="ord_test", events=[])
    
    record = memory.record(case, stream)
    assert record is None, "Should reject if evidence IDs are empty"

def test_learning_accepted_with_full_provenance():
    memory = OutcomeMemory()
    case = AssuranceCase(
        case_id="TEST-5",
        order_id="ord_test",
        status=AssuranceCaseStatus.ASSURED,
        outcome_verified=True,
        provenance_source="webhook",
        provenance_record_id="evt_123",
        provenance_evidence_ids=["evt_123"]
    )
    stream = EventStream(order_id="ord_test", events=[])
    
    record = memory.record(case, stream)
    assert record is not None, "Should accept when all provenance and verification rules are met"
    assert record.outcome_verified == True
    assert record.source_type == "webhook"
    assert record.source_record_id == "evt_123"
