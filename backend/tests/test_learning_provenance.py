import pytest
from datetime import datetime, timezone
from app.db.database import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import OutcomeRecordModel
from app.cases.assurance import AssuranceCase, AssuranceCaseStatus, ViolationType, RecommendedAction
from app.models.event import EventStream, FinancialEvent, EventType, EventSource
from app.learning.memory import OutcomeMemory
from app.db.repository import AssuranceRepository

@pytest.fixture(scope="function")
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    yield db
    db.close()

def test_rejects_unverified_resolution(session):
    repo = AssuranceRepository(session)
    memory = OutcomeMemory(repo)
    
    stream = EventStream(order_id="ord_1", events=[])
    repo.save_stream(stream)
    
    case = AssuranceCase(
        case_id="C-1",
        order_id="ord_1",
        status=AssuranceCaseStatus.ASSURED,
        outcome_verified=True,
        outcome_details=None, # Missing proof
        violation_type=ViolationType.DUPLICATE_COLLECTION
    )
    repo.save_case(case, "ord_1")
    memory.record(case, stream)
    
    with pytest.raises(ValueError, match="cryptographic proof"):
        memory.mark_resolved(case, "REFUND_DUPLICATE")

def test_rejects_missing_provenance_fields(session):
    repo = AssuranceRepository(session)
    memory = OutcomeMemory(repo)
    
    stream = EventStream(order_id="ord_2", events=[])
    repo.save_stream(stream)
    
    case = AssuranceCase(
        case_id="C-2",
        order_id="ord_2",
        status=AssuranceCaseStatus.ASSURED,
        outcome_verified=True,
        outcome_details={"note": "verified manually"}, # Missing mode and verification
        violation_type=ViolationType.DUPLICATE_COLLECTION
    )
    repo.save_case(case, "ord_2")
    memory.record(case, stream)
    
    with pytest.raises(ValueError, match="strict provenance fields"):
        memory.mark_resolved(case, "REFUND_DUPLICATE")

def test_rejects_missing_evidence_linkage(session):
    repo = AssuranceRepository(session)
    memory = OutcomeMemory(repo)
    
    stream = EventStream(order_id="ord_3", events=[])
    repo.save_stream(stream)
    
    case = AssuranceCase(
        case_id="C-3",
        order_id="ord_3",
        status=AssuranceCaseStatus.ASSURED,
        outcome_verified=True,
        outcome_details={"mode": "manual", "verification": "ok"},
        exposure_details={"gross_exposure": 100}, # Missing relevant_event_ids
        violation_type=ViolationType.DUPLICATE_COLLECTION
    )
    repo.save_case(case, "ord_3")
    memory.record(case, stream)
    
    with pytest.raises(ValueError, match="causal evidence linkage"):
        memory.mark_resolved(case, "REFUND_DUPLICATE")

def test_accepts_valid_provenance(session):
    repo = AssuranceRepository(session)
    memory = OutcomeMemory(repo)
    
    stream = EventStream(order_id="ord_4", events=[])
    repo.save_stream(stream)
    
    case = AssuranceCase(
        case_id="C-4",
        order_id="ord_4",
        status=AssuranceCaseStatus.ASSURED,
        outcome_verified=True,
        outcome_details={"mode": "webhook", "verification": "ok", "refund_id": "ref_1"},
        exposure_details={"relevant_event_ids": ["evt_1"]},
        violation_type=ViolationType.DUPLICATE_COLLECTION
    )
    repo.save_case(case, "ord_4")
    memory.record(case, stream)
    
    record = memory.mark_resolved(case, "REFUND_DUPLICATE")
    
    assert record.source_type == "webhook"
    assert record.source_record_id == "ref_1"
    assert record.verification_evidence_ids == ["evt_1"]
    
    # Check DB
    db_record = session.query(OutcomeRecordModel).filter_by(case_id="C-4").first()
    assert db_record.source_type == "webhook"
    assert db_record.source_record_id == "ref_1"
