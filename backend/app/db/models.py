from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, JSON, Enum as SQLEnum, ForeignKey, func
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from app.db.database import Base
from app.cases.assurance import AssuranceCaseStatus, RecommendedAction
from app.models.event import EventType, EventSource

class EventStreamModel(Base):
    __tablename__ = "streams"
    order_id = Column(String, primary_key=True, index=True)
    merchant_id = Column(String, index=True)
    events = relationship("FinancialEventModel", back_populates="stream", cascade="all, delete-orphan", order_by="FinancialEventModel.timestamp")
    cases = relationship("AssuranceCaseModel", back_populates="stream", cascade="all, delete-orphan")

class FinancialEventModel(Base):
    __tablename__ = "events"
    event_id = Column(String, primary_key=True, index=True)
    order_id = Column(String, ForeignKey("streams.order_id"), index=True)
    event_type = Column(SQLEnum(EventType), nullable=False)
    source = Column(SQLEnum(EventSource), nullable=False)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    merchant_id = Column(String, nullable=True)
    payment_id = Column(String, nullable=True)
    refund_id = Column(String, nullable=True)
    amount = Column(Float, nullable=True)
    caused_by_event_id = Column(String, nullable=True)
    
    stream = relationship("EventStreamModel", back_populates="events")

class AssuranceCaseModel(Base):
    __tablename__ = "cases"
    case_id = Column(String, primary_key=True, index=True)
    order_id = Column(String, ForeignKey("streams.order_id"), index=True)
    status = Column(SQLEnum(AssuranceCaseStatus), default=AssuranceCaseStatus.OPEN)
    severity = Column(String, nullable=True)
    violation_type = Column(String, nullable=True)
    workflow = Column(String, nullable=True)
    pattern_status = Column(String, default="KNOWN")
    pattern_hash = Column(String, index=True, nullable=True)
    human_classification = Column(JSON, nullable=True)
    financial_exposure = Column(Float, default=0.0)
    confidence = Column(Float, nullable=True)
    causal_summary = Column(String, nullable=True)
    recommended_action = Column(SQLEnum(RecommendedAction), nullable=True)
    evidence_event_ids = Column(JSON, default=list)
    outcome_details = Column(JSON, nullable=True)
    resolution_note = Column(String, nullable=True)
    
    stream = relationship("EventStreamModel", back_populates="cases")

class OutcomeRecordModel(Base):
    __tablename__ = "outcome_records"
    case_id = Column(String, primary_key=True, index=True)
    violation_type = Column(String, index=True, nullable=True)
    pattern_hash = Column(String, index=True, nullable=True)
    features = Column(JSON, nullable=False)
    resolved = Column(Boolean, default=False)
    recommended_action = Column(String, nullable=True)
    human_approved_action = Column(String, nullable=True)
    actual_action = Column(String, nullable=True)
    final_status = Column(String, nullable=True)
    outcome_verified = Column(Boolean, default=False)
    
    # Provenance fields
    source_type = Column(String, nullable=True)
    source_record_id = Column(String, nullable=True)
    verification_evidence_ids = Column(JSON, nullable=True)
    model_version = Column(String, nullable=True)

    resolution_duration_seconds = Column(Float, nullable=True)
    financial_exposure = Column(Float, nullable=True)
    action_amount = Column(Float, nullable=True)
    verified_amount_recovered = Column(Float, nullable=True)
    remaining_exposure = Column(Float, nullable=True)
    recorded_at = Column(DateTime(timezone=True), default=func.now())

class PatternRecordModel(Base):
    """
    Stores verified mappings between a deterministic event sequence (hashed)
    and the human-classified violation type.
    """
    __tablename__ = "pattern_records"
    pattern_hash = Column(String, primary_key=True, index=True)
    canonical_sequence = Column(JSON, nullable=False)
    classified_violation = Column(String, nullable=False)
    first_observed_at = Column(DateTime(timezone=True), server_default=func.now())
    occurrences = Column(Integer, default=1)

class WebhookDeliveryModel(Base):
    __tablename__ = "webhook_deliveries"
    event_id = Column(String, primary_key=True, index=True)
    delivered_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class RefundCorrelationModel(Base):
    __tablename__ = "refund_correlations"
    refund_id = Column(String, primary_key=True, index=True)
    case_id = Column(String, index=True, nullable=False)

class ModelVersionModel(Base):
    __tablename__ = "model_versions"
    model_version = Column(String, primary_key=True, index=True)
    status = Column(String, index=True, nullable=False) # CANDIDATE, VALIDATED, ACTIVE, REJECTED
    trained_at = Column(DateTime(timezone=True), default=func.now())
    training_example_count = Column(Integer, nullable=False)
    validation_f1 = Column(Float, nullable=True)
    precision = Column(Float, nullable=True)
    recall = Column(Float, nullable=True)
    artifact_path = Column(String, nullable=False)

class VerifiedCleanObservationModel(Base):
    """
    Stores verified clean event streams (NO_VIOLATION) as Risk=0 training examples.
    """
    __tablename__ = "verified_clean_observations"
    order_id = Column(String, primary_key=True, index=True)
    features = Column(JSON, nullable=False)
    recorded_at = Column(DateTime(timezone=True), default=func.now())
