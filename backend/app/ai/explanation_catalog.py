from app.cases.assurance import ViolationType, RecommendedAction

EXPLANATION_CATALOG = {
    ViolationType.DUPLICATE_COLLECTION: {
        "title": "Duplicate Collection",
        "what_happened": "The same order resulted in more than one successful collection.",
        "root_cause": "The original payment later completed after an automated retry had already captured successfully.",
        "why_flagged": "Multiple successful captures were associated with the same financial intent."
    },
    ViolationType.PAYMENT_AMOUNT_MISMATCH: {
        "title": "Payment Amount Mismatch",
        "what_happened": "The captured payment amount differs from the expected order amount.",
        "root_cause": "The payment gateway processed a partial or mismatched amount for the transaction.",
        "why_flagged": "The captured sum is inconsistent with the required financial expectation."
    },
    ViolationType.UNCERTAIN_PAYMENT_CAPTURED: {
        "title": "Uncertain Payment Captured",
        "what_happened": "A payment previously marked as uncertain or timed-out unexpectedly succeeded.",
        "root_cause": "The transaction state drifted asynchronously and resulted in a delayed success.",
        "why_flagged": "A collection occurred outside the synchronous tracking window."
    },
    ViolationType.REFUND_EXCEEDS_CAPTURED: {
        "title": "Refund Exceeds Captured",
        "what_happened": "The total refunded amount exceeds the total captured amount for the order.",
        "root_cause": "Multiple overlapping refunds or misconfigured refunds were issued.",
        "why_flagged": "The calculated remaining exposure indicates a negative balance."
    },
    ViolationType.REFUND_REVERSAL: {
        "title": "Refund Reversal",
        "what_happened": "A previously requested refund was reversed or cancelled by the provider.",
        "root_cause": "The provider encountered an error or rejection while processing the refund.",
        "why_flagged": "The expected refund completion was interrupted by a reversal event."
    },
    ViolationType.REFUND_NOT_COMPLETED: {
        "title": "Refund Not Completed",
        "what_happened": "A requested refund has not reached a completed state.",
        "root_cause": "The refund workflow stalled or is waiting on downstream clearing.",
        "why_flagged": "The expected refund completion event was not observed."
    },
    ViolationType.DUPLICATE_REFUND: {
        "title": "Duplicate Refund",
        "what_happened": "The same order received multiple refund executions for the same transaction.",
        "root_cause": "Concurrent refund requests or provider retries caused double refunds.",
        "why_flagged": "More refunds were processed than requested or expected."
    },
    ViolationType.SETTLEMENT_VARIANCE: {
        "title": "Settlement Variance",
        "what_happened": "The settlement amount does not match the amount expected from the captured payment activity.",
        "root_cause": "The settlement reconciliation produced an unexplained amount difference.",
        "why_flagged": "The provider settlement amount differs from the reconstructed expected amount."
    },
    ViolationType.SETTLEMENT_UNEXPLAINED: {
        "title": "Settlement Unexplained",
        "what_happened": "A settlement was received but cannot be attributed to expected captured payments.",
        "root_cause": "Funds were settled without a corresponding capture event in the system.",
        "why_flagged": "Orphaned settlement records were detected."
    },
    ViolationType.DISPUTE_EVIDENCE_CONTRADICTION: {
        "title": "Dispute Evidence Contradiction",
        "what_happened": "The submitted dispute evidence contradicts the recorded transactional truth.",
        "root_cause": "The evidence payload does not match the reconstructed event state.",
        "why_flagged": "A discrepancy exists between what happened and what is being claimed."
    },
    ViolationType.DISPUTE_MISSING_EVIDENCE: {
        "title": "Dispute Missing Evidence",
        "what_happened": "A dispute was created but required evidence is missing.",
        "root_cause": "The dispute workflow did not receive the necessary documentation.",
        "why_flagged": "The dispute lacks the evidence required to contest or evaluate it."
    },
    ViolationType.DISPUTE_ALREADY_REFUNDED: {
        "title": "Dispute Already Refunded",
        "what_happened": "A dispute was raised for a transaction that has already been refunded.",
        "root_cause": "The customer or issuer initiated a chargeback on a previously resolved order.",
        "why_flagged": "Dispute lifecycle overlaps with a successful refund lifecycle."
    },
    ViolationType.DISPUTE_DEADLINE_RISK: {
        "title": "Dispute Deadline Risk",
        "what_happened": "A dispute is approaching its response deadline.",
        "root_cause": "The SLA for submitting evidence is dangerously close to expiring.",
        "why_flagged": "Immediate action is required to prevent an automatic dispute loss."
    },
    ViolationType.AUTOMATED_DISPUTE_CONTESTED: {
        "title": "Automated Dispute Contested",
        "what_happened": "An automated dispute resolution process was contested.",
        "root_cause": "The automated decision was appealed or requires manual intervention.",
        "why_flagged": "The default dispute outcome is under review."
    },
    ViolationType.COLLECTION_AFTER_CANCELLATION: {
        "title": "Collection After Cancellation",
        "what_happened": "A payment was collected after the order was explicitly cancelled.",
        "root_cause": "The gateway processed a transaction on a terminated intent.",
        "why_flagged": "Funds were captured for an invalid or cancelled order."
    },
    ViolationType.AMOUNT_MISMATCH: {
        "title": "Amount Mismatch",
        "what_happened": "An amount mismatch was detected between related financial events.",
        "root_cause": "Amounts across lifecycle stages (e.g., auth vs capture) do not align.",
        "why_flagged": "The financial continuity of the transaction is broken."
    },
    ViolationType.CONFLICTING_AGENT_ACTION: {
        "title": "Conflicting Agent Action",
        "what_happened": "Contradictory actions were performed by human or automated agents.",
        "root_cause": "Agents initiated overlapping workflows (e.g., simultaneous retry and refund).",
        "why_flagged": "The state machine detected unsafe concurrent operations."
    },
    ViolationType.REFUND_SLA_BREACH: {
        "title": "Refund SLA Breach",
        "what_happened": "The refund remained unresolved beyond the expected refund completion window.",
        "root_cause": "The requested refund did not receive a successful provider completion within the required SLA.",
        "why_flagged": "The refund completion evidence was not received within the configured resolution window."
    },
    ViolationType.REFUND_FAILURE: {
        "title": "Refund Failure",
        "what_happened": "The refund was requested but the provider reported that the refund failed.",
        "root_cause": "The recovery action did not complete successfully at the provider.",
        "why_flagged": "The requested refund has no confirmed successful completion event."
    },
    ViolationType.REFUND_WITHOUT_CAPTURE: {
        "title": "Refund Without Capture",
        "what_happened": "A refund was attempted or processed for a payment that was never captured.",
        "root_cause": "The refund workflow operated on an unauthorized or uncaptured transaction.",
        "why_flagged": "Funds are being returned without corresponding initial collection."
    },
    ViolationType.UNEXPECTED_AGENT_REFUND: {
        "title": "Unexpected Agent Refund",
        "what_happened": "An agent initiated a refund that does not align with the standard workflow.",
        "root_cause": "A manual refund was triggered outside the expected resolution path.",
        "why_flagged": "An unprompted refund action was detected."
    },
    ViolationType.MISSING_SETTLEMENT: {
        "title": "Missing Settlement",
        "what_happened": "The expected settlement for captured payments is missing.",
        "root_cause": "The provider has not settled the collected funds within the standard payout window.",
        "why_flagged": "Captured funds have not been reconciled with a settlement event."
    },
    ViolationType.SETTLEMENT_AMOUNT_MISMATCH: {
        "title": "Settlement Amount Mismatch",
        "what_happened": "The settlement amount differs from the specific transaction captures.",
        "root_cause": "The settlement batch contains discrepancies compared to individual captures.",
        "why_flagged": "A mismatch exists between transaction-level and batch-level financials."
    },
    ViolationType.UNEXPLAINED_ADJUSTMENT: {
        "title": "Unexplained Adjustment",
        "what_happened": "An unexplained adjustment was applied to the account or transaction.",
        "root_cause": "The provider introduced a fee or adjustment that lacks corresponding context.",
        "why_flagged": "The financial balance was altered by an unknown event."
    },
    ViolationType.CROSS_CYCLE_DISCREPANCY: {
        "title": "Cross Cycle Discrepancy",
        "what_happened": "A discrepancy exists across multiple billing or settlement cycles.",
        "root_cause": "Transactions span cycles in a way that breaks reconciliation logic.",
        "why_flagged": "Cross-cycle financial accounting does not align."
    },
    ViolationType.CONTESTED_RESOLUTION: {
        "title": "Contested Resolution",
        "what_happened": "A previously resolved case or dispute has been contested.",
        "root_cause": "The outcome of a resolution is being disputed or reviewed.",
        "why_flagged": "The finality of a case has been challenged."
    },
    ViolationType.NO_VIOLATION: {
        "title": "No Violation",
        "what_happened": "The financial event stream matched all invariant rules.",
        "root_cause": "The transaction followed a completely normal and expected lifecycle.",
        "why_flagged": "No deterministic anomalies were detected."
    },
    ViolationType.LATE_EVIDENCE: {
        "title": "Late Evidence",
        "what_happened": "Required dispute evidence was submitted after the allowed deadline.",
        "root_cause": "The dispute workflow did not receive the required evidence within the permitted submission window.",
        "why_flagged": "The evidence submission timestamp exceeded the dispute deadline."
    },
    ViolationType.FUNDS_WITHHELD_INCORRECTLY: {
        "title": "Funds Withheld Incorrectly",
        "what_happened": "Funds were withheld incorrectly by the provider.",
        "root_cause": "A chargeback or hold was applied without proper justification or alignment.",
        "why_flagged": "The provider's withholding action contradicts the expected state."
    },
    ViolationType.MISSING_CHARGEBACK_DEDUCTION: {
        "title": "Missing Chargeback Deduction",
        "what_happened": "A dispute was lost but the corresponding chargeback deduction is missing.",
        "root_cause": "The financial penalty for a lost dispute has not been realized.",
        "why_flagged": "The expected settlement deduction for a dispute is absent."
    },
    ViolationType.CONCURRENT_DISPUTE_REFUND: {
        "title": "Concurrent Dispute Refund",
        "what_happened": "A dispute and a refund are occurring concurrently for the same transaction.",
        "root_cause": "The system detected overlapping recovery actions (dispute and refund).",
        "why_flagged": "Dual resolution paths present a double-exposure risk."
    }
}
