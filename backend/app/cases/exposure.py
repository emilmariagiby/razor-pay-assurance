from dataclasses import dataclass, field
from typing import List, Optional
from app.models.event import EventStream, EventType
from app.cases.assurance import AssuranceCase, ViolationType

@dataclass
class ExposureResult:
    expected_amount: Optional[int]
    actual_amount: Optional[int]
    gross_exposure: Optional[int]
    recovery_initiated: Optional[int]
    verified_recovery: Optional[int]
    remaining_exposure: Optional[int]
    financially_applicable: bool = True
    currency: str = "INR"
    relevant_event_ids: List[str] = field(default_factory=list)
    calculation_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "expected_amount": self.expected_amount,
            "actual_amount": self.actual_amount,
            "gross_exposure": self.gross_exposure,
            "recovery_initiated": self.recovery_initiated,
            "verified_recovery": self.verified_recovery,
            "remaining_exposure": self.remaining_exposure,
            "financially_applicable": self.financially_applicable,
            "currency": self.currency,
            "relevant_event_ids": self.relevant_event_ids,
            "calculation_reason": self.calculation_reason,
        }

class ExposureCalculator:
    """
    Authoritative deterministic engine for deriving financial exposure from an event stream.
    Replaces separate/competing calculations across the app.
    """
    
    def calculate(self, case: AssuranceCase, stream: EventStream) -> ExposureResult:
        """
        Derive financial exposure from the stream and the core violation.
        """
        relevant_event_ids = []
        expected_amount: Optional[int] = 0
        actual_amount: Optional[int] = 0
        gross_exposure: Optional[int] = 0
        reason = ""
        financially_applicable = True
        
        # Determine gross exposure based on the violation and stream context
        if case.violation_type == ViolationType.DUPLICATE_COLLECTION:
            # Expected: 1 successful payment. Actual: >1 successful payments.
            successful_payments = [e for e in stream.events if e.event_type == EventType.PAYMENT_CAPTURED]
            if successful_payments:
                expected_amount = successful_payments[0].amount
                actual_amount = sum(e.amount for e in successful_payments)
                gross_exposure = actual_amount - expected_amount
                relevant_event_ids.extend(e.event_id for e in successful_payments)
                reason = "Multiple payments captured for single order."
                
        elif case.violation_type == ViolationType.PAYMENT_AMOUNT_MISMATCH:
            # E.g. expected 100, got 50.
            payments = [e for e in stream.events if e.event_type == EventType.PAYMENT_CAPTURED]
            if payments:
                actual_amount = sum((e.amount or 0) for e in payments)
                expected_amount = case.financial_exposure + actual_amount # derived fallback
                gross_exposure = case.financial_exposure
                relevant_event_ids.extend(e.event_id for e in payments)
                reason = "Payment amount does not match expected amount."
                
        elif case.violation_type == ViolationType.REFUND_EXCEEDS_CAPTURED:
            payments = sum((e.amount or 0) for e in stream.events if e.event_type == EventType.PAYMENT_CAPTURED)
            refunds = sum((e.amount or 0) for e in stream.events if e.event_type in (EventType.REFUND_COMPLETED, EventType.REFUND_PROCESSED))
            expected_amount = payments
            actual_amount = refunds
            gross_exposure = max(0, refunds - payments)
            reason = "Total refunded exceeds total captured."
            
        elif case.violation_type == ViolationType.MISSING_SETTLEMENT:
            payments = sum((e.amount or 0) for e in stream.events if e.event_type == EventType.PAYMENT_CAPTURED)
            expected_amount = payments
            actual_amount = 0
            gross_exposure = payments
            reason = "Expected settlement missing for captured payments."
            
        elif case.violation_type in (
            ViolationType.LATE_EVIDENCE,
            ViolationType.DISPUTE_MISSING_EVIDENCE,
            ViolationType.DISPUTE_DEADLINE_RISK,
            ViolationType.DISPUTE_EVIDENCE_CONTRADICTION
        ):
            # Non-financial violations unless concrete amount is at risk
            if case.financial_exposure and case.financial_exposure > 0:
                gross_exposure = case.financial_exposure
                expected_amount = case.financial_exposure
                actual_amount = 0
                financially_applicable = True
                reason = "Derived from invariant reported exposure."
            else:
                financially_applicable = False
                expected_amount = None
                actual_amount = None
                gross_exposure = None
                reason = "Monetary exposure is not semantically applicable for this workflow."
                
        else:
            # Fallback to the invariant's reported exposure if we don't have specialized logic
            gross_exposure = case.financial_exposure
            expected_amount = case.financial_exposure
            actual_amount = 0
            reason = f"Derived from {case.violation_type.value if case.violation_type else 'unknown'} invariant."

        # Calculate recoveries (Idempotent per refund_id)
        recovery_initiated = 0
        verified_recovery = 0
        
        # Track unique refunds to avoid duplicate counting of events for the same refund_id
        processed_refunds = set()
        
        for e in stream.events:
            if e.event_type == EventType.REFUND_REQUESTED and e.refund_id not in processed_refunds:
                recovery_initiated += (e.amount or 0)
                processed_refunds.add(e.refund_id)
                relevant_event_ids.append(e.event_id)
                
        # Re-iterate or look at completed separately (a refund might skip requested state in webhooks)
        completed_refund_ids = set()
        for e in stream.events:
            if e.event_type in (EventType.REFUND_COMPLETED, EventType.REFUND_PROCESSED) and e.refund_id not in completed_refund_ids:
                verified_recovery += (e.amount or 0)
                completed_refund_ids.add(e.refund_id)
                relevant_event_ids.append(e.event_id)
                
                # If we didn't see a REQUESTED event for this, add it to initiated as well to balance
                if e.refund_id not in processed_refunds:
                    recovery_initiated += (e.amount or 0)
                    processed_refunds.add(e.refund_id)

        # A failed refund cancels its initiated amount logically for remaining exposure?
        # Actually, if it failed, it didn't recover anything.
        failed_refund_ids = {e.refund_id for e in stream.events if e.event_type == EventType.REFUND_FAILED}
        for rid in failed_refund_ids:
            if rid in processed_refunds and rid not in completed_refund_ids:
                # If it failed and wasn't completed, it shouldn't count towards active recovery initiated
                # (Or we just leave it in initiated but it never reaches verified)
                pass 
                
        remaining_exposure = None
        if financially_applicable and gross_exposure is not None:
            remaining_exposure = max(0, gross_exposure - verified_recovery)
            
        # If not financially applicable, recoveries shouldn't technically matter or they are just zero.
        if not financially_applicable:
            recovery_initiated = None
            verified_recovery = None
        
        return ExposureResult(
            expected_amount=expected_amount,
            actual_amount=actual_amount,
            gross_exposure=gross_exposure,
            recovery_initiated=recovery_initiated,
            verified_recovery=verified_recovery,
            remaining_exposure=remaining_exposure,
            financially_applicable=financially_applicable,
            currency="INR",
            relevant_event_ids=list(set(relevant_event_ids)),
            calculation_reason=reason
        )
