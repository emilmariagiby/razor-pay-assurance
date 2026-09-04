from sqlalchemy.orm import Session
from app.db.models import EventStreamModel, FinancialEventModel, AssuranceCaseModel, OutcomeRecordModel
from app.models.event import EventStream, FinancialEvent
from app.cases.assurance import AssuranceCase, AssuranceCaseStatus, CaseTimelineStep, RecommendedAction, ViolationType, PatternStatus
from app.learning.memory import OutcomeRecord

class AssuranceRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---------------------------------------------------------
    # Streams & Events
    # ---------------------------------------------------------
    def get_stream(self, order_id: str) -> EventStream | None:
        model = self.db.query(EventStreamModel).filter(EventStreamModel.order_id == order_id).first()
        if not model:
            return None
        stream = EventStream(order_id=model.order_id, merchant_id=model.merchant_id)
        for event_model in model.events:
            stream.add(self._to_event_domain(event_model))
        return stream

    def save_stream(self, stream: EventStream) -> None:
        if not stream.order_id:
            return
            
        model = self.db.query(EventStreamModel).filter(EventStreamModel.order_id == stream.order_id).first()
        if not model:
            model = EventStreamModel(order_id=stream.order_id, merchant_id=stream.merchant_id)
            self.db.add(model)
        
        # Upsert events (in a real system, would use merge or ignore conflicts)
        existing_event_ids = {e.event_id for e in model.events}
        for event in stream.events:
            if event.event_id not in existing_event_ids:
                event_model = self._to_event_model(event, stream.order_id)
                self.db.add(event_model)
                
        self.db.commit()

    def _to_event_domain(self, model: FinancialEventModel) -> FinancialEvent:
        return FinancialEvent(
            event_id=model.event_id,
            event_type=model.event_type,
            source=model.source,
            timestamp=model.timestamp,
            merchant_id=model.merchant_id,
            order_id=model.order_id,
            payment_id=model.payment_id,
            refund_id=model.refund_id,
            amount=model.amount,
            caused_by_event_id=model.caused_by_event_id,
        )

    def _to_event_model(self, event: FinancialEvent, order_id: str) -> FinancialEventModel:
        return FinancialEventModel(
            event_id=event.event_id,
            order_id=order_id,
            event_type=event.event_type,
            source=event.source,
            timestamp=event.timestamp,
            merchant_id=event.merchant_id,
            payment_id=event.payment_id,
            refund_id=event.refund_id,
            amount=event.amount,
            caused_by_event_id=event.caused_by_event_id,
        )

    # ---------------------------------------------------------
    # Cases
    # ---------------------------------------------------------
    def get_case(self, case_id: str) -> AssuranceCase | None:
        model = self.db.query(AssuranceCaseModel).filter(AssuranceCaseModel.case_id == case_id).first()
        if not model:
            return None
        return self._to_case_domain(model)

    def list_cases(self, workflow: str = None, severity: str = None, status: str = None) -> list[AssuranceCase]:
        query = self.db.query(AssuranceCaseModel)
        if workflow:
            query = query.filter(AssuranceCaseModel.workflow == workflow)
        if severity:
            query = query.filter(AssuranceCaseModel.severity == severity.upper())
        if status:
            query = query.filter(AssuranceCaseModel.status == status.upper())
        
        models = query.all()
        return [self._to_case_domain(m) for m in models]
        
    def get_cases_for_order(self, order_id: str) -> list[AssuranceCase]:
        models = self.db.query(AssuranceCaseModel).filter(AssuranceCaseModel.order_id == order_id).all()
        return [self._to_case_domain(m) for m in models]

    def remove_cases_for_order(self, order_id: str) -> None:
        self.db.query(AssuranceCaseModel).filter(AssuranceCaseModel.order_id == order_id).delete()
        self.db.commit()

    def save_case(self, case: AssuranceCase, order_id: str) -> None:
        model = self.db.query(AssuranceCaseModel).filter(AssuranceCaseModel.case_id == case.case_id).first()
        if not model:
            model = AssuranceCaseModel(case_id=case.case_id, order_id=order_id)
            self.db.add(model)
            
        model.status = case.status
        model.severity = case.severity
        model.violation_type = case.violation_type.value if case.violation_type else None
        model.workflow = case.workflow
        model.pattern_status = case.pattern_status.value if case.pattern_status else "KNOWN"
        model.pattern_hash = case.pattern_hash
        model.human_classification = case.human_classification
        model.financial_exposure = case.financial_exposure
        model.confidence = case.confidence
        model.causal_summary = case.causal_summary
        model.recommended_action = case.recommended_action
        model.evidence_event_ids = case.evidence_event_ids
        model.outcome_details = case.outcome_details
        model.resolution_note = case.resolution_note
        
        self.db.commit()

    def _to_case_domain(self, model: AssuranceCaseModel) -> AssuranceCase:
        case = AssuranceCase(
            case_id=model.case_id,
            violation_type=ViolationType(model.violation_type) if model.violation_type else None,
            workflow=model.workflow,
            financial_exposure=model.financial_exposure,
            evidence_event_ids=model.evidence_event_ids,
        )
        case.status = model.status
        case.severity = model.severity
        case.pattern_status = PatternStatus(model.pattern_status) if model.pattern_status else PatternStatus.KNOWN
        case.pattern_hash = model.pattern_hash
        case.human_classification = model.human_classification
        case.confidence = model.confidence
        case.causal_summary = model.causal_summary
        case.recommended_action = model.recommended_action
        case.outcome_details = model.outcome_details
        case.resolution_note = model.resolution_note
        case.order_id = model.order_id
        return case

    # ---------------------------------------------------------
    # ML Memory (Verified Clean Observations)
    # ---------------------------------------------------------
    def get_clean_observations(self):
        from app.db.models import VerifiedCleanObservationModel
        from app.learning.features import OutcomeFeatures
        models = self.db.query(VerifiedCleanObservationModel).all()
        records = []
        for m in models:
            records.append({
                "order_id": m.order_id,
                "features": OutcomeFeatures(**m.features),
                "recorded_at": m.recorded_at
            })
        return records

    def save_clean_observation(self, order_id: str, features_dict: dict) -> None:
        from app.db.models import VerifiedCleanObservationModel
        model = self.db.query(VerifiedCleanObservationModel).filter(VerifiedCleanObservationModel.order_id == order_id).first()
        if not model:
            model = VerifiedCleanObservationModel(order_id=order_id)
            self.db.add(model)
        model.features = features_dict
        self.db.commit()

    # ---------------------------------------------------------
    # ML Memory (Resolved Incidents)
    # ---------------------------------------------------------
    def get_memory_records(self) -> list[OutcomeRecord]:
        from app.learning.features import OutcomeFeatures
        models = self.db.query(OutcomeRecordModel).all()
        records = []
        for m in models:
            records.append(OutcomeRecord(
                case_id=m.case_id,
                features=OutcomeFeatures.from_dict(m.features),
                violation_type=m.violation_type,
                pattern_hash=m.pattern_hash,
                resolved=m.resolved,
                recommended_action=m.recommended_action,
                human_approved_action=m.human_approved_action,
                actual_action=m.actual_action,
                final_status=m.final_status,
                outcome_verified=m.outcome_verified,
                resolution_duration_seconds=m.resolution_duration_seconds,
                financial_exposure=m.financial_exposure,
                action_amount=m.action_amount,
                verified_amount_recovered=m.verified_amount_recovered,
                remaining_exposure=m.remaining_exposure,
                recorded_at=m.recorded_at,
                source_type=m.source_type,
                source_record_id=m.source_record_id,
                verification_evidence_ids=m.verification_evidence_ids,
                model_version=m.model_version
            ))
        return records

    def save_memory_record(self, record: OutcomeRecord) -> None:
        model = self.db.query(OutcomeRecordModel).filter(OutcomeRecordModel.case_id == record.case_id).first()
        if not model:
            model = OutcomeRecordModel(case_id=record.case_id)
            self.db.add(model)
            
        model.features = record.features.to_dict()
        model.violation_type = record.violation_type
        model.pattern_hash = record.pattern_hash
        model.resolved = record.resolved
        model.recommended_action = record.recommended_action
        model.human_approved_action = record.human_approved_action
        model.actual_action = record.actual_action
        model.final_status = record.final_status
        model.outcome_verified = record.outcome_verified
        model.resolution_duration_seconds = record.resolution_duration_seconds
        model.financial_exposure = record.financial_exposure
        model.action_amount = record.action_amount
        model.verified_amount_recovered = record.verified_amount_recovered
        model.remaining_exposure = record.remaining_exposure
        model.recorded_at = record.recorded_at
        model.source_type = record.source_type
        model.source_record_id = record.source_record_id
        model.verification_evidence_ids = record.verification_evidence_ids
        model.model_version = record.model_version
        
        self.db.commit()

        self.db.commit()

    # ---------------------------------------------------------
    # Pattern Memory
    # ---------------------------------------------------------
    def get_pattern_record(self, pattern_hash: str) -> dict | None:
        from app.db.models import PatternRecordModel
        model = self.db.query(PatternRecordModel).filter(PatternRecordModel.pattern_hash == pattern_hash).first()
        if not model:
            return None
        return {
            "pattern_hash": model.pattern_hash,
            "canonical_sequence": model.canonical_sequence,
            "classified_violation": model.classified_violation,
            "first_observed_at": model.first_observed_at.isoformat() if model.first_observed_at else None,
            "occurrences": model.occurrences
        }

    def save_pattern_record(self, pattern_hash: str, canonical_sequence: list[str], classified_violation: str) -> None:
        from app.db.models import PatternRecordModel
        model = self.db.query(PatternRecordModel).filter(PatternRecordModel.pattern_hash == pattern_hash).first()
        if not model:
            model = PatternRecordModel(
                pattern_hash=pattern_hash,
                canonical_sequence=canonical_sequence,
                classified_violation=classified_violation,
                occurrences=1
            )
            self.db.add(model)
        else:
            model.occurrences += 1
            # Update the violation type if it changed
            model.classified_violation = classified_violation
        self.db.commit()

    # ---------------------------------------------------------
    # Webhooks & Correlations
    # ---------------------------------------------------------
    def is_webhook_processed(self, event_id: str) -> bool:
        from app.db.models import WebhookDeliveryModel
        return self.db.query(WebhookDeliveryModel).filter(WebhookDeliveryModel.event_id == event_id).first() is not None

    def mark_webhook_processed(self, event_id: str) -> None:
        from app.db.models import WebhookDeliveryModel
        if not self.is_webhook_processed(event_id):
            model = WebhookDeliveryModel(event_id=event_id)
            self.db.add(model)
            self.db.commit()

    def correlate_refund_to_case(self, refund_id: str, case_id: str) -> None:
        from app.db.models import RefundCorrelationModel
        model = self.db.query(RefundCorrelationModel).filter(RefundCorrelationModel.refund_id == refund_id).first()
        if not model:
            model = RefundCorrelationModel(refund_id=refund_id, case_id=case_id)
            self.db.add(model)
        else:
            model.case_id = case_id
        self.db.commit()

    def get_case_for_refund(self, refund_id: str) -> AssuranceCase | None:
        from app.db.models import RefundCorrelationModel
        model = self.db.query(RefundCorrelationModel).filter(RefundCorrelationModel.refund_id == refund_id).first()
        if not model:
            return None
        return self.get_case(model.case_id)
