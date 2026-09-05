import pytest
from fastapi.testclient import TestClient
from app.db.database import engine, Base
from main import app
from app.cases.assurance import PatternStatus, AssuranceCaseStatus, ViolationType, RecommendedAction

@pytest.fixture
def client() -> TestClient:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return TestClient(app)

def test_pattern_learning_loop(client: TestClient) -> None:
    # --- 1. Create custom UNKNOWN case ---
    custom_stream = {
        "name": "Agent retry after cancellation",
        "amount_inr": 25000,
        "order_id": "ord_pattern_1",
        "events": [
            {"event_type": "payment.created", "order_id": "ord_pattern_1", "payment_id": "pay_1", "amount": 2500000, "timestamp": "2026-09-02T10:00:00Z", "source": "gateway"},
            {"event_type": "payment.authorized", "order_id": "ord_pattern_1", "payment_id": "pay_1", "amount": 2500000, "timestamp": "2026-09-02T10:01:00Z", "source": "gateway"},
            {"event_type": "payment.captured", "order_id": "ord_pattern_1", "payment_id": "pay_1", "amount": 2500000, "timestamp": "2026-09-02T10:02:00Z", "source": "gateway"},
            {"event_type": "payment.created", "order_id": "ord_pattern_1", "payment_id": "pay_2", "amount": 2500000, "timestamp": "2026-09-02T10:03:00Z", "source": "gateway"},
            {"event_type": "payment.authorized", "order_id": "ord_pattern_1", "payment_id": "pay_2", "amount": 2500000, "timestamp": "2026-09-02T10:03:30Z", "source": "gateway"},
            {"event_type": "payment.captured", "order_id": "ord_pattern_1", "payment_id": "pay_2", "amount": 2500000, "timestamp": "2026-09-02T10:04:00Z", "source": "gateway"},
        ]
    }
    
    resp = client.post("/assurance/cases", json=custom_stream)
    assert resp.status_code == 200
    cases = resp.json()["cases"]
    assert len(cases) == 1
    case1 = cases[0]
    
    assert case1["pattern_status"] == PatternStatus.KNOWN.value
    assert case1["violation_type"] == ViolationType.DUPLICATE_COLLECTION.value
    assert case1["status"] == AssuranceCaseStatus.OPEN.value
    case_id_1 = case1["case_id"]

    # --- 3. Resolution ---
    # Case is OPEN, we can refund
    refund_resp = client.post(f"/assurance/cases/{case_id_1}/actions/refund", json={"payment_id": "pay_2"})
    assert refund_resp.status_code == 200
    resolved_case = refund_resp.json()["case"]
    assert resolved_case["status"] == AssuranceCaseStatus.ASSURED.value

    # --- 4. Future Recognition ---
    # Create a SECOND custom case with DIFFERENT IDs but same structure
    custom_stream_2 = {
        "name": "Another cancellation retry",
        "amount_inr": 18000,
        "order_id": "ord_pattern_2",
        "events": [
            {"event_type": "payment.created", "order_id": "ord_pattern_2", "payment_id": "pay_9", "amount": 1800000, "timestamp": "2026-09-02T11:00:00Z", "source": "gateway"},
            {"event_type": "payment.authorized", "order_id": "ord_pattern_2", "payment_id": "pay_9", "amount": 1800000, "timestamp": "2026-09-02T11:01:00Z", "source": "gateway"},
            {"event_type": "payment.captured", "order_id": "ord_pattern_2", "payment_id": "pay_9", "amount": 1800000, "timestamp": "2026-09-02T11:02:00Z", "source": "gateway"},
            {"event_type": "payment.created", "order_id": "ord_pattern_2", "payment_id": "pay_X", "amount": 1800000, "timestamp": "2026-09-02T11:03:00Z", "source": "gateway"},
            {"event_type": "payment.authorized", "order_id": "ord_pattern_2", "payment_id": "pay_X", "amount": 1800000, "timestamp": "2026-09-02T11:03:30Z", "source": "gateway"},
            {"event_type": "payment.captured", "order_id": "ord_pattern_2", "payment_id": "pay_X", "amount": 1800000, "timestamp": "2026-09-02T11:04:00Z", "source": "gateway"},
        ]
    }
    
    resp2 = client.post("/assurance/cases", json=custom_stream_2)
    assert resp2.status_code == 200
    cases2 = resp2.json()["cases"]
    assert len(cases2) == 1
    case2 = cases2[0]
    
    # It should have matched the pattern!
    assert case2["pattern_status"] == PatternStatus.KNOWN.value
    assert case2["violation_type"] == ViolationType.DUPLICATE_COLLECTION.value
    case_id_2 = case2["case_id"]

    # --- 5. Verify Recommendation from Memory ---
    rec_resp = client.get(f"/assurance/cases/{case_id_2}/recommendation")
    assert rec_resp.status_code == 200
    rec = rec_resp.json()
    assert rec["similar_cases"] == 1
    assert rec["successful_cases"] == 1
    assert rec["recommended_action"] == RecommendedAction.REFUND_DUPLICATE.value

    # --- 6. Verify distinct pattern hashes ---
    # Third case, different sequence
    custom_stream_3 = {
        "name": "Different pattern",
        "amount_inr": 18000,
        "order_id": "ord_pattern_3",
        "events": [
            {"event_type": "payment.created", "order_id": "ord_pattern_3", "payment_id": "pay_9", "amount": 1800000, "timestamp": "2026-09-02T12:00:00Z", "source": "gateway"},
            {"event_type": "payment.authorized", "order_id": "ord_pattern_3", "payment_id": "pay_9", "amount": 1800000, "timestamp": "2026-09-02T12:01:00Z", "source": "gateway"},
            {"event_type": "payment.captured", "order_id": "ord_pattern_3", "payment_id": "pay_9", "amount": 1800000, "timestamp": "2026-09-02T12:02:00Z", "source": "gateway"},
            {"event_type": "refund.requested", "order_id": "ord_pattern_3", "payment_id": "pay_9", "refund_id": "ref_9", "amount": 2000000, "timestamp": "2026-09-02T12:03:00Z", "source": "gateway"},
        ]
    }
    
    resp3 = client.post("/assurance/cases", json=custom_stream_3)
    assert resp3.status_code == 200
    cases3 = resp3.json()["cases"]
    assert len(cases3) > 0
    case3 = next(c for c in cases3 if c["violation_type"] == ViolationType.REFUND_EXCEEDS_CAPTURED.value)
    
    # It should be KNOWN because it is a deterministic violation
    assert case3["pattern_status"] == PatternStatus.KNOWN.value
