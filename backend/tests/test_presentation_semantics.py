import pytest
from app.models.event import EventStream, FinancialEvent, EventType, EventSource
from app.cases.assurance import AssuranceCase, ViolationType, RecommendedAction, AssuranceCaseStatus
from app.ai.explainer import explain_case
from app.cases.exposure import ExposureCalculator
from app.learning.memory import OutcomeMemory
from app.db.repository import AssuranceRepository
from datetime import datetime, timezone

def test_explanations_are_semantic():
    cases = [
        ViolationType.LATE_EVIDENCE,
        ViolationType.REFUND_FAILURE,
        ViolationType.SETTLEMENT_VARIANCE,
        ViolationType.DUPLICATE_COLLECTION,
        ViolationType.DISPUTE_MISSING_EVIDENCE
    ]
    
    explanations = []
    for vt in cases:
        case = AssuranceCase(
            case_id="TEST-1",
            order_id="ord_test",
            status=AssuranceCaseStatus.OPEN,
            violation_type=vt,
            recommended_action=RecommendedAction.ESCALATE
        )
        exp = explain_case(case)
        assert "Causal chain of" not in exp.root_cause
        assert exp.why_flagged != ""
        explanations.append(exp.summary)
        
    # Ensure they are all unique
    assert len(set(explanations)) == len(explanations)

def test_financial_applicability_and_exposure():
    calc = ExposureCalculator()
    
    # 1. Non-financial case
    c1 = AssuranceCase(case_id="1", order_id="ord_1", status=AssuranceCaseStatus.OPEN, violation_type=ViolationType.LATE_EVIDENCE)
    stream1 = EventStream(order_id="ord_1", events=[])
    res1 = calc.calculate(c1, stream1)
    
    assert res1.financially_applicable is False
    assert res1.expected_amount is None
    assert res1.actual_amount is None
    assert res1.gross_exposure is None
    
    # 2. Financially applicable genuine zero exposure (e.g. SETTLEMENT_VARIANCE where it magically matches or REFUND_EXCEEDS_CAPTURED where refund=0 and capture=0)
    c2 = AssuranceCase(case_id="2", order_id="ord_2", status=AssuranceCaseStatus.OPEN, violation_type=ViolationType.REFUND_EXCEEDS_CAPTURED)
    stream2 = EventStream(order_id="ord_2", events=[])
    res2 = calc.calculate(c2, stream2)
    
    assert res2.financially_applicable is True
    assert res2.expected_amount == 0
    assert res2.actual_amount == 0
    assert res2.gross_exposure == 0
    
    # 3. Concrete financial exposure overrides non-financial default
    c3 = AssuranceCase(case_id="3", order_id="ord_3", status=AssuranceCaseStatus.OPEN, violation_type=ViolationType.LATE_EVIDENCE, financial_exposure=1500)
    res3 = calc.calculate(c3, stream1)
    assert res3.financially_applicable is True
    assert res3.expected_amount == 1500

class MockRiskModel:
    def evaluate_risk(self, features, status):
        return {"assurance_risk": -1.0, "external_behavior_signal": None}
class MockAnomalyDetector:
    def is_anomaly(self, features):
        return False
        
class MockRepo:
    def get_memory_records(self): return []

def test_risk_semantics():
    repo = MockRepo()
    memory = OutcomeMemory(repo)
    memory.risk_model = MockRiskModel()
    memory.anomaly_detector = MockAnomalyDetector()
    
    stream = EventStream(order_id="ord_1", events=[])
    
    # 1. NO_VIOLATION -> 0.0
    c_clean = AssuranceCase(case_id="1", order_id="ord_1", status=AssuranceCaseStatus.OPEN, violation_type=ViolationType.NO_VIOLATION)
    r1 = memory.risk_for(c_clean, stream)
    assert r1["risk_score"] == 0.0
    
    # 2. ML unavailable -> None
    c_violation = AssuranceCase(case_id="2", order_id="ord_1", status=AssuranceCaseStatus.OPEN, violation_type=ViolationType.DUPLICATE_COLLECTION, confidence=0.8)
    r2 = memory.risk_for(c_violation, stream)
    assert r2["risk_score"] is None
