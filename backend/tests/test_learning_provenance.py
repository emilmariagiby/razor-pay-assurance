import pytest
from app.cases.assurance import AssuranceCase, AssuranceCaseStatus
from app.models.event import EventStream, FinancialEvent
from app.learning.memory import OutcomeMemory
from app.db.repository import AssuranceRepository
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

@pytest.fixture
def memory_with_repo():
    engine = create_engine('sqlite:///:memory:')
    from app.db.models import Base
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    repo = AssuranceRepository(Session())
    memory = OutcomeMemory(repository=repo)
    return memory

def test_learning_rejected_without_assured_status(memory_with_repo):
    case = AssuranceCase(case_id="TEST-1", order_id="ord_1", status=AssuranceCaseStatus.OPEN)
    memory_with_repo.record(case, EventStream(order_id="ord_1", events=[]))
    
    # Resolve it with wrong status
    case.status = AssuranceCaseStatus.RESOLVING
    case.outcome_verified = True
    case.provenance_source = "test"
    case.provenance_record_id = "evt_1"
    case.provenance_evidence_ids = ["evt_1"]
    
    # It shouldn't raise, but it shouldn't mark it resolved for learning
    record = memory_with_repo.mark_resolved(case, "refund")
    assert record.resolved == False

def test_learning_rejected_without_verification(memory_with_repo):
    case = AssuranceCase(case_id="TEST-2", order_id="ord_1", status=AssuranceCaseStatus.OPEN)
    memory_with_repo.record(case, EventStream(order_id="ord_1", events=[]))
    
    case.status = AssuranceCaseStatus.ASSURED
    case.outcome_verified = False
    
    record = memory_with_repo.mark_resolved(case, "refund")
    assert record.resolved == True
    assert not record.source_type # Provenance block skipped if not verified

def test_learning_raises_without_provenance_source(memory_with_repo):
    case = AssuranceCase(case_id="TEST-3", order_id="ord_1", status=AssuranceCaseStatus.OPEN)
    memory_with_repo.record(case, EventStream(order_id="ord_1", events=[]))
    
    case.status = AssuranceCaseStatus.ASSURED
    case.outcome_verified = True
    case.provenance_source = ""
    case.provenance_record_id = "evt_1"
    case.provenance_evidence_ids = ["evt_1"]
    
    with pytest.raises(ValueError, match="missing strict provenance fields"):
        memory_with_repo.mark_resolved(case, "refund")

def test_learning_raises_without_evidence_ids(memory_with_repo):
    case = AssuranceCase(case_id="TEST-4", order_id="ord_1", status=AssuranceCaseStatus.OPEN)
    memory_with_repo.record(case, EventStream(order_id="ord_1", events=[]))
    
    case.status = AssuranceCaseStatus.ASSURED
    case.outcome_verified = True
    case.provenance_source = "test"
    case.provenance_record_id = "evt_1"
    case.provenance_evidence_ids = []
    
    with pytest.raises(ValueError, match="missing causal evidence linkage"):
        memory_with_repo.mark_resolved(case, "refund")

def test_learning_accepted_with_full_provenance(memory_with_repo):
    case = AssuranceCase(case_id="TEST-5", order_id="ord_1", status=AssuranceCaseStatus.OPEN)
    memory_with_repo.record(case, EventStream(order_id="ord_1", events=[]))
    
    case.status = AssuranceCaseStatus.ASSURED
    case.outcome_verified = True
    case.provenance_source = "webhook"
    case.provenance_record_id = "evt_123"
    case.provenance_evidence_ids = ["evt_123"]
    case.provenance_model_version = "v3_verified"
    
    record = memory_with_repo.mark_resolved(case, "refund")
    assert record.outcome_verified == True
    assert record.source_type == "webhook"
    assert record.source_record_id == "evt_123"
    assert record.verification_evidence_ids == ["evt_123"]
    assert record.model_version == "v3_verified"
