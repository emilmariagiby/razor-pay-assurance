import pytest
from fastapi.testclient import TestClient
from app.db.database import engine, Base
from app.db.repository import AssuranceRepository
from tests.test_api import get_scenario
from main import app
from app.cases.assurance import AssuranceCaseStatus

@pytest.fixture
def client() -> TestClient:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return TestClient(app)

def test_e2e_learning_loop_validation(client: TestClient) -> None:
    # --- A. DETECT PROOF ---
    # 1. Create a realistic assurance case (DUPLICATE_COLLECTION)
    stream1 = get_scenario("late_auth_duplicate")
    stream1.order_id = "ord_e2e_1"
    
    # 2. Detect the violation
    analyze_resp = client.post("/assurance/analyze", json={"stream": stream1.model_dump(mode="json")})
    assert analyze_resp.status_code == 200
    cases1 = analyze_resp.json()["cases"]
    case1 = next(c for c in cases1 if c["violation_type"] == "DUPLICATE_COLLECTION")
    case_id_1 = case1["case_id"]
    
    assert case1["status"] == "OPEN"
    assert case1["recommended_action"] == "REFUND_DUPLICATE"

    # --- B. RESOLVE PROOF ---
    # 3. Approve the recommended action
    approve_resp = client.post(f"/assurance/cases/{case_id_1}/approve", json={"note": "Approved by e2e test"})
    assert approve_resp.status_code == 200
    assert approve_resp.json()["case"]["status"] == "PENDING"

    # 4. Execute simulated resolution (this triggers simulation in routes.py which marks it ASSURED eventually)
    refund_resp = client.post(f"/assurance/cases/{case_id_1}/actions/refund", json={"payment_id": "pay_A"})
    assert refund_resp.status_code == 200
    resolved_case = refund_resp.json()["case"]
    
    # --- C. VERIFY PROOF ---
    # 5 & 6. Verify it becomes ASSURED and outcome_verified = true
    assert resolved_case["status"] == "ASSURED"
    assert resolved_case["outcome_verified"] is True

    # --- D. REMEMBER PROOF ---
    # 7 & 8. Persist and verify meaning values in DB
    from app.db.database import get_db
    db = next(get_db())
    repo = AssuranceRepository(db)
    records = repo.get_memory_records()
    record1 = next(r for r in records if r.case_id == case_id_1)
    
    assert record1.violation_type == "DUPLICATE_COLLECTION"
    assert record1.financial_exposure == 2500000
    assert record1.recommended_action == "REFUND_DUPLICATE"
    assert record1.human_approved_action == "REFUND_DUPLICATE"
    assert record1.action_amount == 2500000
    assert record1.verified_amount_recovered == 2500000
    assert record1.remaining_exposure == 0
    assert record1.resolution_duration_seconds >= 0
    assert record1.final_status == "ASSURED"
    assert record1.outcome_verified is True
    
    # --- F. PERSISTENCE PROOF ---
    # 9. In this test context, we can't truly restart the process, but we can clear the repository instance
    # to ensure it reads from DB.
    repo2 = AssuranceRepository(db)
    persisted_records = repo2.get_memory_records()
    assert len([r for r in persisted_records if r.case_id == case_id_1]) == 1

    # --- E. RECOMMEND PROOF ---
    # 10. Create a SECOND similar case
    stream2 = get_scenario("late_auth_duplicate")
    stream2.order_id = "ord_e2e_2"
    client.post("/assurance/analyze", json={"stream": stream2.model_dump(mode="json")})
    
    cases2 = client.get("/assurance/cases").json()["cases"]
    case_id_2 = next(c["case_id"] for c in cases2 if c["order_id"] == "ord_e2e_2" and c["violation_type"] == "DUPLICATE_COLLECTION")
    
    # 11 & 12. Query recommendation and prove derived from first outcome
    rec_resp = client.get(f"/assurance/cases/{case_id_2}/recommendation")
    assert rec_resp.status_code == 200
    rec_data = rec_resp.json()
    assert rec_data["similar_cases"] == 1
    assert rec_data["successful_cases"] == 1
    assert rec_data["recommended_action"] == "REFUND_DUPLICATE"
    assert rec_data["success_rate"] == 1.0


def test_multiple_paths_and_insufficient_history(client: TestClient) -> None:
    # --- G. MULTIPLE-PATH RANKING PROOF ---
    # We will simulate multiple outcomes directly via memory injection to test ranking
    from app.db.database import get_db
    db = next(get_db())
    repo = AssuranceRepository(db)
    from app.learning.memory import OutcomeRecord
    from app.learning.features import OutcomeFeatures
    import datetime
    
    dummy_features = OutcomeFeatures(
        workflow="retry", 
        violation_type="DUPLICATE_COLLECTION", 
        severity="HIGH", 
        event_count=0, 
        payment_count=0, 
        capture_count=0, 
        agent_action_count=0, 
        has_timeout=False, 
        exposure=0,
        unique_event_type_count=1,
        sequence_length=1,
        retry_count=0,
        timeout_count=0,
        cancellation_count=0,
        refund_count=0,
        settlement_count=0,
        dispute_count=0,
        has_retry=False,
        has_cancellation=False,
        has_refund=False,
        has_settlement=False
    )
    # 1 unverified REFUND_DUPLICATE attempt
    repo.save_memory_record(OutcomeRecord(
        case_id="case_unverified_1", features=dummy_features, violation_type="DUPLICATE_COLLECTION",
        actual_action="REFUND_DUPLICATE", final_status="PENDING", outcome_verified=False,
        recorded_at=datetime.datetime.now(datetime.timezone.utc)
    ))
    # 1 ESCALATE -> ASSURED
    repo.save_memory_record(OutcomeRecord(
        case_id="case_escalate_1", features=dummy_features, violation_type="DUPLICATE_COLLECTION",
        actual_action="ESCALATE", final_status="ASSURED", outcome_verified=True,
        recorded_at=datetime.datetime.now(datetime.timezone.utc), resolution_duration_seconds=10
    ))
    # 2 REFUND_DUPLICATE -> ASSURED
    repo.save_memory_record(OutcomeRecord(
        case_id="case_refund_1", features=dummy_features, violation_type="DUPLICATE_COLLECTION",
        actual_action="REFUND_DUPLICATE", final_status="ASSURED", outcome_verified=True,
        recorded_at=datetime.datetime.now(datetime.timezone.utc), resolution_duration_seconds=5
    ))
    repo.save_memory_record(OutcomeRecord(
        case_id="case_refund_2", features=dummy_features, violation_type="DUPLICATE_COLLECTION",
        actual_action="REFUND_DUPLICATE", final_status="ASSURED", outcome_verified=True,
        recorded_at=datetime.datetime.now(datetime.timezone.utc), resolution_duration_seconds=7
    ))

    # Now create a new case and test recommendation
    stream = get_scenario("late_auth_duplicate")
    stream.order_id = "ord_multi_1"
    client.post("/assurance/analyze", json={"stream": stream.model_dump(mode="json")})
    
    cases = client.get("/assurance/cases").json()["cases"]
    case_id = next(c["case_id"] for c in cases if c["order_id"] == "ord_multi_1" and c["violation_type"] == "DUPLICATE_COLLECTION")
    
    rec_resp = client.get(f"/assurance/cases/{case_id}/recommendation")
    rec_data = rec_resp.json()
    
    assert rec_data["similar_cases"] == 4
    # Unverified is excluded from successful paths
    # Total paths:
    # ESCALATE: 1 attempt, 1 success (100%)
    # REFUND_DUPLICATE: 3 attempts (1 unverified, 2 assured), 2 successes (66.6%)
    # Wait, the logic ranks primarily by success rate, then by number of successes.
    # ESCALATE has 100% success rate, REFUND_DUPLICATE has 66.6% success rate.
    # Therefore, ESCALATE should win!
    assert rec_data["recommended_action"] == "ESCALATE"
    assert rec_data["success_rate"] == 1.0


def test_insufficient_history(client: TestClient) -> None:
    # --- H. INSUFFICIENT-HISTORY PROOF ---
    # Create a completely new case with no history
    stream = get_scenario("settlement_variance")
    stream.order_id = "ord_insuff_1"
    client.post("/assurance/analyze", json={"stream": stream.model_dump(mode="json")})
    
    cases = client.get("/assurance/cases").json()["cases"]
    case_id = next(c["case_id"] for c in cases if c["order_id"] == "ord_insuff_1")
    
    rec_resp = client.get(f"/assurance/cases/{case_id}/recommendation")
    rec_data = rec_resp.json()
    
    assert rec_data["similar_cases"] == 0
    assert rec_data["confidence"] is None
    assert "Insufficient verified historical outcomes" in rec_data["reason"]
