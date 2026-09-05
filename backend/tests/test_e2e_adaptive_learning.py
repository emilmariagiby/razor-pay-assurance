import pytest
from app.db.database import SessionLocal, Base, engine
from app.api.routes import create_custom_case, CreateCaseRequest
from app.cases.assurance import AssuranceCaseStatus
from app.api.learning import get_status, train_model
from fastapi import HTTPException

@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()

def test_adaptive_learning_rejects_insufficient_data(db):
    # Ensure there are no verified examples
    status = get_status(db)
    assert status["status"] == "INSUFFICIENT ML TRAINING DATA"
    
    with pytest.raises(HTTPException) as excinfo:
        train_model(db)
    assert "Insufficient verified data" in str(excinfo.value.detail)

def test_clean_observation_persisted_correctly(db):
    # Submit a clean stream (no violations)
    clean_request = CreateCaseRequest(
        name="Test Clean",
        order_id="ord_clean_test",
        amount_inr=1000,
        events=[
            {"event_type": "payment.created", "payment_id": "pay_clean", "amount_inr": 1000, "source": "gateway", "timestamp": "2026-09-02T10:00:00Z"},
            {"event_type": "payment.authorized", "payment_id": "pay_clean", "amount_inr": 1000, "source": "gateway", "timestamp": "2026-09-02T10:01:00Z"},
            {"event_type": "payment.captured", "payment_id": "pay_clean", "amount_inr": 1000, "source": "gateway", "timestamp": "2026-09-02T10:02:00Z"}
        ]
    )
    
    from app.api.routes import analyze, AnalyzeRequest
    from app.models.event import EventStream
    
    stream = EventStream(events=clean_request.events, order_id="ord_clean_test")
    analyze_response = analyze(AnalyzeRequest(stream=stream), db)
    
    assert len(analyze_response.cases) == 0
    
    # Now check if VerifiedCleanObservationModel has it
    from app.db.models import VerifiedCleanObservationModel
    clean_obs = db.query(VerifiedCleanObservationModel).filter(VerifiedCleanObservationModel.order_id == "ord_clean_test").first()
    
    assert clean_obs is not None
    assert clean_obs.features["sequence_length"] == 3
    assert clean_obs.features["exposure"] == 0
