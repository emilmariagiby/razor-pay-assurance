import pytest
from fastapi.testclient import TestClient
from app.api.routes import router
from app.db.models import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import FastAPI
from app.api.routes import get_db
from sqlalchemy.pool import StaticPool
import uuid

app = FastAPI()
app.include_router(router)

@pytest.fixture
def test_client():
    engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        try:
            db = TestingSessionLocal()
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)

def test_valid_custom_case_successfully_persists_and_returns_real_id(test_client):
    """Rules a and d: valid custom case persists and returns real ID"""
    order_id = f"ord_{uuid.uuid4().hex[:6]}"
    response = test_client.post("/assurance/cases", json={
        "name": "Valid Case",
        "order_id": order_id,
        "amount_inr": 1000,
        "events": [
            {"event_type": "payment.created", "order_id": order_id, "payment_id": "pay_1", "amount": 100000, "timestamp": "2026-09-02T09:50:00Z", "source": "gateway"},
            {"event_type": "payment.captured", "order_id": order_id, "payment_id": "pay_1", "amount": 100000, "timestamp": "2026-09-02T10:00:00Z", "source": "gateway"},
            {"event_type": "refund.requested", "order_id": order_id, "payment_id": "pay_1", "refund_id": "ref_1", "amount": 100000, "timestamp": "2026-09-02T10:00:50Z", "source": "gateway"},
            {"event_type": "refund.processed", "order_id": order_id, "payment_id": "pay_1", "refund_id": "ref_1", "amount": 100000, "timestamp": "2026-09-02T10:01:00Z", "source": "gateway"},
            {"event_type": "refund.requested", "order_id": order_id, "payment_id": "pay_1", "refund_id": "ref_2", "amount": 100000, "timestamp": "2026-09-02T10:01:50Z", "source": "gateway"},
            {"event_type": "refund.processed", "order_id": order_id, "payment_id": "pay_1", "refund_id": "ref_2", "amount": 100000, "timestamp": "2026-09-02T10:02:00Z", "source": "gateway"}
        ]
    })
    
    assert response.status_code == 200
    data = response.json()
    assert "cases" in data
    assert len(data["cases"]) > 0
    # verify returns real case id
    assert data["cases"][0]["case_id"].startswith("A-")
    
def test_no_violation_custom_case_does_not_fabricate(test_client):
    """Rule f: no-violation custom case does not get a fabricated violation"""
    response = test_client.post("/assurance/cases", json={
        "name": "Clean Workflow",
        "order_id": "ord_clean",
        "amount_inr": 1000,
        "events": [
            {"event_type": "payment.created", "order_id": "ord_clean", "payment_id": "pay_1", "amount": 100000, "timestamp": "2026-09-02T10:00:00Z", "source": "gateway"},
            {"event_type": "payment.authorized", "order_id": "ord_clean", "payment_id": "pay_1", "amount": 100000, "timestamp": "2026-09-02T10:01:00Z", "source": "gateway"},
            {"event_type": "payment.captured", "order_id": "ord_clean", "payment_id": "pay_1", "amount": 100000, "timestamp": "2026-09-02T10:02:00Z", "source": "gateway"}
        ]
    })
    assert response.status_code == 200
    data = response.json()
    assert data["cases"] == [] # Backend correctly detects NO violation

def test_validation_error_returns_422(test_client):
    """Backend validation error returns 422"""
    response = test_client.post("/assurance/cases", json={
        "name": "Invalid Enum",
        "order_id": "ord_invalid",
        "amount_inr": 1000,
        "events": [
            {"event_type": "payment.madeup", "order_id": "ord_invalid", "payment_id": "pay_1", "amount": 100000, "timestamp": "2026-09-02T10:00:00Z", "source": "gateway"},
        ]
    })
    assert response.status_code == 422

