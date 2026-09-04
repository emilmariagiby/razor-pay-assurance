import pytest
from datetime import datetime, timezone, timedelta
from app.cases.assurance import AssuranceCase, AssuranceCaseStatus
from app.models.event import EventStream, FinancialEvent, EventType, EventSource
from app.learning.memory import OutcomeMemory
from app.db.database import get_db
from app.db.repository import AssuranceRepository

def test_successful_provider_confirmed_refund_assured():
    case = AssuranceCase(financial_exposure=25000, status=AssuranceCaseStatus.RESOLVING)
    
    expected = {"action": "refund", "amount": 25000, "status": "completed"}
    observed = {"action": "refund", "amount": 25000, "status": "completed"}
    
    outcome = {"refund_id": "ref_123", "verification": "WEBHOOK_CONFIRMED"}
    is_verified = case.attempt_verification(expected, observed, outcome)
    
    assert is_verified is True
    assert case.status == AssuranceCaseStatus.ASSURED
    assert case.outcome_verified is True


def test_partial_refund_not_assured():
    case = AssuranceCase(financial_exposure=25000, status=AssuranceCaseStatus.RESOLVING)
    
    expected = {"action": "refund", "amount": 25000, "status": "completed"}
    observed = {"action": "refund", "amount": 10000, "status": "completed"}
    
    is_verified = case.attempt_verification(expected, observed, None)
    
    assert is_verified is False
    assert case.status == AssuranceCaseStatus.PENDING
    assert case.outcome_verified is False


def test_failed_refund_not_assured():
    case = AssuranceCase(financial_exposure=25000, status=AssuranceCaseStatus.RESOLVING)
    
    expected = {"action": "refund", "amount": 25000, "status": "completed"}
    observed = {"action": "refund", "amount": 0, "status": "failed"}
    
    is_verified = case.attempt_verification(expected, observed, None)
    
    assert is_verified is False
    assert case.status == AssuranceCaseStatus.PENDING
    assert case.outcome_verified is False


def test_action_executed_without_provider_confirmation_not_assured():
    case = AssuranceCase(financial_exposure=25000, status=AssuranceCaseStatus.RESOLVING)
    
    expected = {"action": "refund", "amount": 25000, "status": "completed"}
    observed = {"action": "refund", "amount": 25000, "status": "pending"} # Still pending from provider
    
    is_verified = case.attempt_verification(expected, observed, None)
    
    assert is_verified is False
    assert case.status == AssuranceCaseStatus.PENDING


def test_provider_event_contradicts_expected_outcome():
    case = AssuranceCase(financial_exposure=25000, status=AssuranceCaseStatus.RESOLVING)
    
    expected = {"action": "refund", "amount": 25000, "status": "completed"}
    observed = {"action": "chargeback_lost", "amount": 25000, "status": "completed"} 
    
    is_verified = case.attempt_verification(expected, observed, None)
    
    assert is_verified is False
    assert case.status == AssuranceCaseStatus.PENDING


def test_verification_evidence_required():
    # If no expected/observed state is passed (i.e. just trying to mark verified arbitrarily),
    # verify_state_match should fail.
    case = AssuranceCase(financial_exposure=25000, status=AssuranceCaseStatus.RESOLVING)
    
    is_verified = case.attempt_verification({}, {})
    assert is_verified is False
    assert case.status == AssuranceCaseStatus.PENDING


def test_duplicate_provider_event_ignored():
    # We test this logic which resides in routes.py (idempotency check)
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    
    payload = {
        "event": "refund.processed",
        "payload": {
            "refund": {
                "entity": {
                    "id": "rfnd_dup123",
                    "payment_id": "pay_123",
                    "amount": 25000,
                    "status": "processed",
                    "created_at": 1600000000
                }
            }
        }
    }
    
    resp1 = client.post("/assurance/webhooks/razorpay", json=payload)
    assert resp1.status_code == 200
    assert resp1.json()["accepted"] is True
    
    resp2 = client.post("/assurance/webhooks/razorpay", json=payload)
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "duplicate_ignored"
