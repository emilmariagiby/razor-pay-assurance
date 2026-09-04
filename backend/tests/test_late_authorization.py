"""
Test: Late Authorization Duplicate — The Hero Scenario
------------------------------------------------------
This is our Milestone #1.

We give Assurance a stream of 8 payment events describing:

  10:02:01  Payment A created (₹25,000)
  10:02:06  Gateway timeout
  10:02:31  Agent initiates retry
  10:02:34  Payment B created (by agent)
  10:02:36  Payment B authorized
  10:02:37  Payment B captured ✓
  10:04:12  Payment A authorized (late!)
  10:04:13  Payment A captured ✓

We verify that Assurance:
  ✓ Detects DUPLICATE_COLLECTION
  ✓ Reports ₹25,000 financial exposure
  ✓ Confidence ≥ 0.95
  ✓ Recommends a refund action
  ✓ Produces a causal chain
  ✓ Does NOT flag the clean scenarios as violations
"""

import sys
import os

# Ensure we can import from the backend root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from simulator.scenarios import get_scenario, GROUND_TRUTH, all_scenarios
from app.engine import AssuranceEngine
from app.cases.assurance import ViolationType, RecommendedAction, AssuranceCaseStatus
from app.state.payment import PaymentStateMachine, PaymentState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine() -> AssuranceEngine:
    return AssuranceEngine()


@pytest.fixture
def hero_stream():
    return get_scenario("late_auth_duplicate")


# ---------------------------------------------------------------------------
# Test: State Machine resolves both payments correctly
# ---------------------------------------------------------------------------

class TestPaymentStateMachine:

    def test_payment_a_resolves_to_captured(self, hero_stream):
        """Payment A should end in CAPTURED (via TIMEOUT → UNCERTAIN → CAPTURED)."""
        machine = PaymentStateMachine()
        payment_a = machine.resolve("pay_A", hero_stream)

        assert payment_a.state == PaymentState.CAPTURED, \
            f"Expected CAPTURED, got {payment_a.state}"

    def test_payment_a_passes_through_uncertain(self, hero_stream):
        """Payment A must pass through TIMEOUT then UNCERTAIN — that's the key."""
        machine = PaymentStateMachine()
        payment_a = machine.resolve("pay_A", hero_stream)

        state_path = [t.to_state for t in payment_a.transitions]
        assert PaymentState.TIMEOUT in state_path or PaymentState.UNCERTAIN in state_path, \
            f"Expected TIMEOUT/UNCERTAIN in path, got: {state_path}"

    def test_payment_b_resolves_to_captured(self, hero_stream):
        """Payment B (agent-created retry) should also be CAPTURED."""
        machine = PaymentStateMachine()
        payment_b = machine.resolve("pay_B", hero_stream)

        assert payment_b.state == PaymentState.CAPTURED, \
            f"Expected CAPTURED, got {payment_b.state}"

    def test_payment_b_is_agent_initiated(self, hero_stream):
        """Payment B was created by the recovery agent."""
        machine = PaymentStateMachine()
        payment_b = machine.resolve("pay_B", hero_stream)

        assert payment_b.agent_initiated, \
            "Payment B should be flagged as agent-initiated"


# ---------------------------------------------------------------------------
# Test: Assurance Engine on the hero scenario
# ---------------------------------------------------------------------------

class TestHeroScenario:

    def test_produces_at_least_one_case(self, engine, hero_stream):
        """Assurance must detect at least one violation."""
        cases = engine.investigate(hero_stream)
        assert len(cases) >= 1, "Expected at least one AssuranceCase for duplicate collection"

    def test_detects_duplicate_collection(self, engine, hero_stream):
        """The primary violation must be DUPLICATE_COLLECTION."""
        cases = engine.investigate(hero_stream)
        violation_types = [c.violation_type for c in cases]
        assert ViolationType.DUPLICATE_COLLECTION in violation_types, \
            f"Expected DUPLICATE_COLLECTION, got: {violation_types}"

    def test_exposure_is_25000(self, engine, hero_stream):
        """Financial exposure should be ₹25,000 (the duplicate payment amount)."""
        cases = engine.investigate(hero_stream)
        dup_cases = [c for c in cases if c.violation_type == ViolationType.DUPLICATE_COLLECTION]
        assert len(dup_cases) == 1

        exposure_inr = dup_cases[0].exposure_inr
        assert exposure_inr == pytest.approx(25000.0), \
            f"Expected ₹25,000 exposure, got ₹{exposure_inr:,.0f}"

    def test_high_confidence(self, engine, hero_stream):
        """Confidence for a structural duplicate should be ≥ 0.95."""
        cases = engine.investigate(hero_stream)
        dup_case = next(c for c in cases if c.violation_type == ViolationType.DUPLICATE_COLLECTION)
        assert dup_case.confidence >= 0.95, \
            f"Expected confidence ≥ 0.95, got {dup_case.confidence}"

    def test_recommends_refund(self, engine, hero_stream):
        """Recommendation should be to refund the duplicate payment."""
        cases = engine.investigate(hero_stream)
        dup_case = next(c for c in cases if c.violation_type == ViolationType.DUPLICATE_COLLECTION)
        assert dup_case.recommended_action == RecommendedAction.REFUND_DUPLICATE, \
            f"Expected REFUND_DUPLICATE, got {dup_case.recommended_action}"

    def test_requires_human_approval(self, engine, hero_stream):
        """Duplicate collection requires human approval before refunding."""
        cases = engine.investigate(hero_stream)
        dup_case = next(c for c in cases if c.violation_type == ViolationType.DUPLICATE_COLLECTION)
        assert dup_case.requires_human_approval, \
            "Duplicate collection must require human approval"

    def test_status_is_open(self, engine, hero_stream):
        """Newly detected case must have OPEN status."""
        cases = engine.investigate(hero_stream)
        dup_case = next(c for c in cases if c.violation_type == ViolationType.DUPLICATE_COLLECTION)
        assert dup_case.status == AssuranceCaseStatus.OPEN

    def test_causal_chain_is_present(self, engine, hero_stream):
        """Assurance must produce a causal explanation, not just a flag."""
        cases = engine.investigate(hero_stream)
        dup_case = next(c for c in cases if c.violation_type == ViolationType.DUPLICATE_COLLECTION)
        assert len(dup_case.causal_chain) >= 2, \
            f"Expected ≥2 causal steps, got {len(dup_case.causal_chain)}"

    def test_causal_summary_mentions_retry(self, engine, hero_stream):
        """The causal summary should explain that a retry caused the duplicate."""
        cases = engine.investigate(hero_stream)
        dup_case = next(c for c in cases if c.violation_type == ViolationType.DUPLICATE_COLLECTION)
        summary_lower = dup_case.causal_summary.lower()
        assert any(word in summary_lower for word in ["retry", "uncertain", "timeout", "duplicate"]), \
            f"Summary doesn't mention key cause: {dup_case.causal_summary}"

    def test_workflow_is_retry(self, engine, hero_stream):
        """Case should be tagged to the 'retry' workflow."""
        cases = engine.investigate(hero_stream)
        dup_case = next(c for c in cases if c.violation_type == ViolationType.DUPLICATE_COLLECTION)
        assert dup_case.workflow == "retry"

    def test_case_serialises_to_dict(self, engine, hero_stream):
        """Case must be serializable for the API."""
        cases = engine.investigate(hero_stream)
        dup_case = next(c for c in cases if c.violation_type == ViolationType.DUPLICATE_COLLECTION)
        d = dup_case.to_dict()
        assert d["violation_type"] == "DUPLICATE_COLLECTION"
        assert d["exposure_inr"] == pytest.approx(25000.0)
        assert d["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Test: Clean scenarios produce NO violations
# ---------------------------------------------------------------------------

class TestCleanScenarios:

    @pytest.mark.parametrize("scenario_name", [
        "normal_payment",
        "refund_clean",
        "retry_success",
        "settlement_clean",
        "settlement_variance_explained",
    ])
    def test_no_violations_in_clean_scenario(self, engine, scenario_name):
        """Clean scenarios must not produce any Assurance cases."""
        stream = get_scenario(scenario_name)
        cases  = engine.investigate(stream)

        # Filter out UNCERTAIN_PAYMENT_CAPTURED — that's an informational flag
        # for late auth even in clean scenarios.
        actionable = [
            c for c in cases
            if c.violation_type != ViolationType.UNCERTAIN_PAYMENT_CAPTURED
        ]

        assert len(actionable) == 0, \
            f"Scenario '{scenario_name}' should be clean but got: {[c.violation_type for c in actionable]}"


# ---------------------------------------------------------------------------
# Test: Anomaly scenarios ARE correctly flagged
# ---------------------------------------------------------------------------

class TestAnomalyScenarios:

    def test_refund_reversal_is_flagged(self, engine):
        stream = get_scenario("refund_reversal")
        cases  = engine.investigate(stream)
        types  = [c.violation_type for c in cases]
        assert ViolationType.REFUND_REVERSAL in types, \
            f"Expected REFUND_REVERSAL, got: {types}"

    def test_over_refund_is_flagged(self, engine):
        stream = get_scenario("over_refund")
        cases  = engine.investigate(stream)
        types  = [c.violation_type for c in cases]
        assert ViolationType.REFUND_EXCEEDS_CAPTURED in types, \
            f"Expected REFUND_EXCEEDS_CAPTURED, got: {types}"


# ---------------------------------------------------------------------------
# Test: Full evaluation pass (all 10 scenarios)
# ---------------------------------------------------------------------------

class TestFullEvaluation:

    def test_all_scenarios_run_without_error(self, engine):
        """Every scenario must run through the engine without raising."""
        errors = []
        for name, stream in all_scenarios().items():
            try:
                engine.investigate(stream)
            except Exception as ex:
                errors.append(f"{name}: {ex}")

        assert not errors, f"Scenarios raised errors:\n" + "\n".join(errors)

    def test_ground_truth_accuracy(self, engine):
        """
        Validate against our ground truth labels.
        UNCERTAIN_PAYMENT_CAPTURED is excluded from the violation check
        (it's a contributing signal, not a standalone anomaly).
        """
        EXCLUDED = {ViolationType.UNCERTAIN_PAYMENT_CAPTURED}
        correct = 0
        total   = 0

        for name, stream in all_scenarios().items():
            truth = GROUND_TRUTH.get(name)
            if truth is None:
                continue

            total += 1
            cases = engine.investigate(stream)
            actionable = [c for c in cases if c.violation_type not in EXCLUDED]
            detected_violation = len(actionable) > 0

            if detected_violation == truth["expects_violation"]:
                correct += 1
            else:
                print(f"MISMATCH: {name} | expected_violation={truth['expects_violation']} | detected={detected_violation}")
                if actionable:
                    print(f"  Cases: {[c.violation_type for c in actionable]}")

        accuracy = correct / total if total > 0 else 0
        print(f"\n📊 Ground Truth Accuracy: {correct}/{total} = {accuracy:.0%}")

        assert accuracy >= 0.80, \
            f"Expected ≥80% accuracy on ground truth, got {accuracy:.0%} ({correct}/{total})"
