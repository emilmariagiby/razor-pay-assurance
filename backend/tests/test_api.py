from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from app.db.database import engine, Base
from app.db.repository import AssuranceRepository
from sqlalchemy.orm import Session
from app.models.event import EventType
from main import app
from simulator.scenarios import get_scenario


@pytest.fixture
def client() -> TestClient:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return TestClient(app)


def analyze_hero(client: TestClient) -> dict:
    stream = get_scenario("late_auth_duplicate")
    response = client.post(
        "/assurance/analyze",
        json={"stream": stream.model_dump(mode="json")},
    )
    assert response.status_code == 200
    return response.json()


def duplicate_case_id(client: TestClient) -> str:
    result = analyze_hero(client)
    return next(
        case["case_id"]
        for case in result["cases"]
        if case["violation_type"] == "DUPLICATE_COLLECTION"
    )


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_analyze_hero(client: TestClient) -> None:
    result = analyze_hero(client)
    duplicate = next(
        case for case in result["cases"]
        if case["violation_type"] == "DUPLICATE_COLLECTION"
    )
    assert duplicate["severity"] == "CRITICAL"
    assert duplicate["financial_exposure"] == 2_500_000
    assert duplicate["status"] == "OPEN"


def test_list_cases(client: TestClient) -> None:
    analyze_hero(client)
    response = client.get("/assurance/cases", params={"workflow": "retry"})
    assert response.status_code == 200
    assert response.json()["total"] == 2


def test_get_case(client: TestClient) -> None:
    case_id = duplicate_case_id(client)
    response = client.get(f"/assurance/cases/{case_id}")
    assert response.status_code == 200
    assert response.json()["case"]["case_id"] == case_id


def test_get_timeline(client: TestClient) -> None:
    case_id = duplicate_case_id(client)
    response = client.get(f"/assurance/cases/{case_id}/timeline")
    assert response.status_code == 200
    event_types = [step["event_type"] for step in response.json()["steps"]]
    assert "payment.timeout" in event_types
    assert "agent.retry_initiated" in event_types
    assert "payment.captured" in event_types


def test_get_graph(client: TestClient) -> None:
    case_id = duplicate_case_id(client)
    response = client.get(f"/assurance/cases/{case_id}/graph")
    assert response.status_code == 200
    graph = response.json()
    assert graph["node_count"] == 8
    assert graph["edge_count"] >= graph["node_count"] - 1
    assert {edge["relation"] for edge in graph["edges"]} >= {"triggered", "preceded", "resolved"}


def test_get_audit(client: TestClient) -> None:
    case_id = duplicate_case_id(client)
    response = client.get(f"/assurance/cases/{case_id}/audit")
    assert response.status_code == 200
    entries = response.json()["entries"]
    assert len(entries) == 8
    assert entries[2]["actor"] == "AGENT"


def test_invalid_case(client: TestClient) -> None:
    response = client.get("/assurance/cases/does-not-exist")
    assert response.status_code == 404


def test_refund_action(client: TestClient) -> None:
    case_id = duplicate_case_id(client)
    response = client.post(
        f"/assurance/cases/{case_id}/actions/refund",
        json={"note": "Approved for demo verification."},
    )
    assert response.status_code == 200
    assert response.json()["case"]["outcome_details"]["refund_id"].startswith("ref_assurance_")


def test_case_becomes_assured(client: TestClient) -> None:
    case_id = duplicate_case_id(client)
    response = client.post(f"/assurance/cases/{case_id}/actions/refund", json={})
    case = response.json()["case"]
    assert response.status_code == 200
    assert case["status"] == "ASSURED"
    assert case["outcome_verified"] is True
    assert case["outcome_details"]["financial_exposure_eliminated"] == 2_500_000


def test_assured_case_survives_refresh_like_reanalysis(client: TestClient) -> None:
    case_id = duplicate_case_id(client)
    resolved = client.post(f"/assurance/cases/{case_id}/actions/refund", json={}).json()["case"]
    refreshed = client.post(
        "/assurance/analyze",
        json={"stream": get_scenario("late_auth_duplicate").model_dump(mode="json")},
    )
    duplicate = next(
        case for case in refreshed.json()["cases"]
        if case["violation_type"] == "DUPLICATE_COLLECTION"
    )
    assert resolved["status"] == "ASSURED"
    assert duplicate["case_id"] == case_id
    assert duplicate["status"] == "ASSURED"


def test_risk_score_exposes_features_and_reason(client: TestClient) -> None:
    case_id = duplicate_case_id(client)
    response = client.get(f"/assurance/cases/{case_id}/risk")
    risk = response.json()["risk"]
    assert response.status_code == 200
    assert risk["features"]["capture_count"] == 2
    assert risk["features"]["has_timeout"] is True
    assert "recommendation" in risk
    assert "reason" in risk


def test_memory_records_case_features(client: TestClient) -> None:
    analyze_hero(client)
    response = client.get("/assurance/memory")
    assert response.status_code == 200
    assert response.json()["total_records"] == 2


def test_razorpay_webhook_normalizes_event(client: TestClient) -> None:
    payload = {
        "event": "payment.captured",
        "created_at": 1787824800,
        "payload": {"payment": {"entity": {
            "id": "pay_webhook_1",
            "order_id": "ord_webhook_1",
            "merchant_id": "merch_001",
            "amount": 125000,
            "currency": "INR",
        }}},
    }
    response = client.post("/webhooks/razorpay", json=payload)
    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["event_type"] == "payment.captured"
    with Session(engine) as db:
        repo = AssuranceRepository(db)
        stream = repo.get_stream("ord_webhook_1")
        assert stream.events[0].source == "razorpay"


def test_razorpay_webhook_rejects_invalid_signature(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "test-secret")
    response = client.post(
        "/webhooks/razorpay",
        json={"event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_1"}}}},
        headers={"x-razorpay-signature": "invalid"},
    )
    assert response.status_code == 401


def test_razorpay_client_is_disabled_by_default(monkeypatch) -> None:
    from app.connectors.razorpay_client import RazorpayClient

    monkeypatch.delenv("RAZORPAY_TEST_MODE", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    assert RazorpayClient.from_environment() is None


def test_refund_webhook_verifies_existing_case(client: TestClient, monkeypatch) -> None:
    class FakeRazorpayClient:
        def create_refund(self, payment_id, amount, notes=None):
            return {"id": "rfnd_test_1", "status": "created"}

    monkeypatch.setattr(
        "app.api.routes.RazorpayClient.from_environment",
        lambda: FakeRazorpayClient(),
    )
    case_id = duplicate_case_id(client)
    action = client.post(f"/assurance/cases/{case_id}/actions/refund", json={})
    assert action.status_code == 200
    assert action.json()["case"]["status"] == "RESOLVING"

    payload = {"event": "refund.processed", "payload": {"refund": {"entity": {
        "id": "rfnd_test_1",
        "payment_id": "pay_r2b",
        "order_id": "ord_r3",
        "amount": 2500000,
    }}}}
    webhook = client.post("/webhooks/razorpay", json=payload)
    assert webhook.status_code == 200
    timeline = client.get(f"/assurance/cases/{case_id}/timeline").json()
    assert any(step["event_type"] == "refund.processed" for step in timeline["steps"])
    assert client.get(f"/assurance/cases/{case_id}").json()["case"]["status"] == "ASSURED"


def test_correlated_duplicate_webhook_does_not_add_event(client: TestClient, monkeypatch) -> None:
    class FakeRazorpayClient:
        def create_refund(self, payment_id, amount, notes=None):
            return {"id": "rfnd_correlated_duplicate", "status": "created"}

    monkeypatch.setattr(
        "app.api.routes.RazorpayClient.from_environment",
        lambda: FakeRazorpayClient(),
    )
    case_id = duplicate_case_id(client)
    client.post(f"/assurance/cases/{case_id}/actions/refund", json={})
    payload = {"event": "refund.processed", "payload": {"refund": {"entity": {
        "id": "rfnd_correlated_duplicate",
        "payment_id": "pay_r2b",
        "order_id": "ord_r3",
        "amount": 2500000,
    }}}}

    first = client.post("/webhooks/razorpay", json=payload)
    event_count = len(client.get(f"/assurance/cases/{case_id}/timeline").json()["steps"])
    second = client.post("/webhooks/razorpay", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate_ignored"
    assert len(client.get(f"/assurance/cases/{case_id}/timeline").json()["steps"]) == event_count


def test_unknown_refund_webhook_creates_no_assurance_case(client: TestClient) -> None:
    payload = {"event": "refund.processed", "payload": {"refund": {"entity": {
        "id": "rfnd_unknown_case",
        "payment_id": "pay_unknown_case",
        "order_id": "ord_unknown_case",
        "amount": 100,
    }}}}
    response = client.post("/webhooks/razorpay", json=payload)

    assert response.status_code == 200
    assert response.json()["status"] == "unknown_refund_ignored"
    assert client.get("/assurance/cases").json()["total"] == 0


def test_duplicate_webhook_delivery_is_ignored(client: TestClient) -> None:
    payload = {"event": "payment.captured", "payload": {"payment": {"entity": {
        "id": "pay_duplicate_webhook",
        "order_id": "ord_duplicate_webhook",
        "amount": 100,
    }}}}
    first = client.post("/webhooks/razorpay", json=payload)
    second = client.post("/webhooks/razorpay", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate_ignored"
    with Session(engine) as db:
        repo = AssuranceRepository(db)
        stream = repo.get_stream("ord_duplicate_webhook")
        assert len(stream.events) == 1


def test_unknown_refund_webhook_is_ignored(client: TestClient) -> None:
    payload = {"event": "refund.processed", "payload": {"refund": {"entity": {
        "id": "rfnd_unknown",
        "payment_id": "pay_unknown",
        "order_id": "ord_unknown",
        "amount": 100,
    }}}}
    response = client.post("/webhooks/razorpay", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "unknown_refund_ignored"


def test_scenario_catalog_covers_all_workflows(client: TestClient) -> None:
    response = client.get("/assurance/scenarios")

    assert response.status_code == 200
    scenarios = response.json()["scenarios"]
    assert len(scenarios) == 45
    assert {scenario["name"] for scenario in scenarios} >= {
        "late_auth_duplicate",
        "refund_reversal",
        "settlement_variance",
        "dispute_contradiction",
    }


@pytest.mark.parametrize(
    ("scenario_name", "violation_type", "workflow"),
    [
        ("refund_reversal", "REFUND_REVERSAL", "refund"),
        ("settlement_variance", "SETTLEMENT_VARIANCE", "settlement"),
        ("dispute_contradiction", "DISPUTE_EVIDENCE_CONTRADICTION", "dispute"),
    ],
)
def test_non_retry_scenarios_use_shared_case_contract(
    client: TestClient,
    scenario_name: str,
    violation_type: str,
    workflow: str,
) -> None:
    response = client.post(f"/assurance/scenarios/{scenario_name}")

    assert response.status_code == 200
    matching = [
        case for case in response.json()["cases"]
        if case["violation_type"] == violation_type
    ]
    assert matching
    assert matching[0]["workflow"] == workflow
    assert matching[0]["status"] == "OPEN"


def test_clean_scenario_returns_no_cases(client: TestClient) -> None:
    response = client.post("/assurance/scenarios/refund_clean")

    assert response.status_code == 200
    assert response.json()["cases"] == []


def test_unknown_scenario_returns_not_found(client: TestClient) -> None:
    response = client.post("/assurance/scenarios/does-not-exist")

    assert response.status_code == 404
