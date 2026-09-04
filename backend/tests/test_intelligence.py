import pytest
from fastapi.testclient import TestClient
from app.db.database import engine, Base
from tests.test_api import get_scenario
from main import app

@pytest.fixture
def client() -> TestClient:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return TestClient(app)

def test_intelligence_empty_history(client: TestClient) -> None:
    # 1. Create a case
    stream = get_scenario("late_auth_duplicate")
    client.post("/assurance/analyze", json={"stream": stream.model_dump(mode="json")})
    
    # 2. Get cases
    response = client.get("/assurance/cases")
    cases = response.json()["cases"]
    case_id = next(c["case_id"] for c in cases if c["violation_type"] == "DUPLICATE_COLLECTION")
    
    # 3. Check recommendation
    response = client.get(f"/assurance/cases/{case_id}/recommendation")
    assert response.status_code == 200
    data = response.json()
    assert data["similar_cases"] == 0
    assert data["confidence"] is None

def test_intelligence_historical_learning(client: TestClient) -> None:
    # 1. Create a duplicate case
    stream1 = get_scenario("late_auth_duplicate")
    stream1.order_id = "ord_learn_1"
    client.post("/assurance/analyze", json={"stream": stream1.model_dump(mode="json")})
    
    cases = client.get("/assurance/cases").json()["cases"]
    case_id = next(c["case_id"] for c in cases if c["order_id"] == "ord_learn_1" and c["violation_type"] == "DUPLICATE_COLLECTION")
    
    # 2. Resolve via simulation (this calls memory.mark_resolved under the hood)
    client.post(f"/assurance/cases/{case_id}/actions/refund", json={"payment_id": "pay_learn_2"})
    
    # 3. Check memory
    memory = client.get(f"/assurance/cases/{case_id}/memory").json()["historical_records"]
    assert len(memory) == 0 # no previous records
    
    # 4. Create SECOND duplicate case
    stream2 = get_scenario("late_auth_duplicate")
    stream2.order_id = "ord_learn_2"
    client.post("/assurance/analyze", json={"stream": stream2.model_dump(mode="json")})
    
    cases = client.get("/assurance/cases").json()["cases"]
    case_id_2 = next(c["case_id"] for c in cases if c["order_id"] == "ord_learn_2" and c["violation_type"] == "DUPLICATE_COLLECTION")
    
    # 5. Check recommendation
    response = client.get(f"/assurance/cases/{case_id_2}/recommendation")
    data = response.json()
    
    assert data["similar_cases"] == 1
    assert data["successful_cases"] == 1
    assert data["recommended_action"] == "REFUND_DUPLICATE"
    assert data["success_rate"] == 1.0
