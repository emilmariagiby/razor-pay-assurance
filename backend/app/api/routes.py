"""
Assurance API Routes
--------------------
Clean adapter layer between HTTP and the AssuranceEngine core.

The engine is treated as a black box here — we only call:
    engine.investigate(stream) -> list[AssuranceCase]

and use AssuranceCase.to_dict() for all serialisation.
"""

from __future__ import annotations

from datetime import timedelta
import os

from fastapi import APIRouter, HTTPException, Request, Depends
from sqlalchemy.orm import Session

from app.api.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    CaseResponse,
    ActionRequest,
    ActionResponse,
    CreateCaseRequest,
    ClassifyRequest,
)
from app.engine import AssuranceEngine
from app.cases.assurance import AssuranceCase, AssuranceCaseStatus, RecommendedAction, PatternStatus, ViolationType
from app.models.event import EventSource, EventStream, EventType, FinancialEvent
from app.ai.explainer import explain_case
from app.graph.causal import CausalGraphBuilder
from app.learning.memory import OutcomeMemory, get_canonical_hash
from app.connectors.razorpay import normalize_webhook, verify_signature
from app.connectors.razorpay_client import RazorpayClient
from simulator.scenarios import GROUND_TRUTH, get_scenario
import uuid
from datetime import datetime, timezone

from app.db.database import get_db
from app.db.repository import AssuranceRepository

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

# Single engine instance — stateless, safe to share across requests
_engine = AssuranceEngine()


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/assurance", tags=["Assurance"])
webhook_router = APIRouter(tags=["Webhooks"])


@router.post("/webhooks/razorpay")
@webhook_router.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    """Normalize one Razorpay webhook and immediately re-evaluate its order."""
    repo = AssuranceRepository(db)
    memory = OutcomeMemory(repo)
    
    body = await request.body()
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")
    signature = request.headers.get("x-razorpay-signature")
    if secret and not verify_signature(body, signature, secret):
        raise HTTPException(status_code=401, detail="Invalid Razorpay webhook signature.")

    try:
        event = normalize_webhook(await request.json())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    # Webhook idempotency: ignore duplicate deliveries of the same event
    if repo.is_webhook_processed(event.event_id):
        return {"accepted": True, "event_id": event.event_id, "status": "duplicate_ignored", "cases": []}
    repo.mark_webhook_processed(event.event_id)

    case = None
    if event.refund_id:
        case = repo.get_case_for_refund(event.refund_id)
        
    if case:
        stream = repo.get_stream(case.order_id)
        if stream is None:
            raise HTTPException(status_code=409, detail="Refund correlation has no event stream.")
    elif event.event_type == EventType.REFUND_PROCESSED:
        return {
            "accepted": True,
            "event_id": event.event_id,
            "status": "unknown_refund_ignored",
            "cases": [],
        }
    else:
        scope = event.order_id or event.merchant_id or "unscoped"
        stream = repo.get_stream(scope)
        if stream is None:
            stream = EventStream(order_id=event.order_id, merchant_id=event.merchant_id)
            
    stream.add(event)
    repo.save_stream(stream)
    
    cases = _engine.investigate(stream)

    # Find existing cases: try refund_id correlation first, then fallback to order_id matching
    related_cases = []
    if event.refund_id:
        case = repo.get_case_for_refund(event.refund_id)
        if case:
            related_cases.append(case)
    if not related_cases:
        related_cases = repo.get_cases_for_order(stream.order_id)

    if event.event_type == EventType.REFUND_PROCESSED or event.event_type == EventType.REFUND_COMPLETED:
        for case in related_cases:
            if case.status == AssuranceCaseStatus.RESOLVING:
                # 1. State Reconstruction from evidence
                from app.cases.exposure import ExposureCalculator
                exposure = ExposureCalculator().calculate(case, stream)
                case.exposure_details = exposure.to_dict()

                # 2. Expected == Observed comparison
                expected_state = {"action": "recovery", "amount": exposure.gross_exposure, "status": "completed"}
                observed_state = {"action": "recovery", "amount": exposure.verified_recovery, "status": "completed" if exposure.remaining_exposure == 0 else "pending"}
                
                outcome_payload = {
                    "refund_id": event.refund_id,
                    "payment_id": event.payment_id,
                    "mode": "razorpay_webhook",
                    "verification": "WEBHOOK_CONFIRMED",
                    "financial_exposure_eliminated": exposure.verified_recovery,
                }
                
                # 3. Attempt verification (enforces expected == observed)
                is_verified = case.attempt_verification(
                    expected_state, 
                    observed_state, 
                    outcome_payload,
                    provenance_source="razorpay_webhook",
                    provenance_record_id=event.event_id,
                    provenance_evidence_ids=[event.payment_id, event.refund_id] if getattr(event, 'refund_id', None) else [event.payment_id],
                    provenance_model_version="v1"
                )
                if is_verified:
                    memory.mark_resolved(case, RecommendedAction.REFUND_DUPLICATE.value)
                cases = [case]
                
    for case in cases:
        repo.save_case(case, stream.order_id)
        memory.record(case, stream)

    return {"accepted": True, "event_id": event.event_id, "event_type": event.event_type, "cases": [case.to_dict() for case in cases]}


# ---------------------------------------------------------------------------
# Endpoint 2: POST /assurance/analyze
# ---------------------------------------------------------------------------

@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest, db: Session = Depends(get_db)):
    """
    Submit an EventStream and receive Assurance Cases.
    """
    repo = AssuranceRepository(db)
    memory = OutcomeMemory(repo)
    stream = request.stream
    
    existing_cases = repo.get_cases_for_order(stream.order_id) if stream.order_id else []
    if any(case.status == AssuranceCaseStatus.ASSURED for case in existing_cases):
        return AnalyzeResponse(cases=[case.to_dict() for case in existing_cases])

    cases = _engine.investigate(stream)
    
    if stream.order_id:
        repo.save_stream(stream)
        repo.remove_cases_for_order(stream.order_id)

        if not cases:
            # Verified Clean Observation (Risk=0)
            from app.learning.features import extract_features
            from app.cases.assurance import AssuranceCase
            clean_case = AssuranceCase(
                workflow="clean",
                severity="NORMAL",
                violation_type=None,
                financial_exposure=0,
                status=AssuranceCaseStatus.ASSURED,
                order_id=stream.order_id
            )
            features = extract_features(clean_case, stream)
            repo.save_clean_observation(stream.order_id, features.to_dict())

    for case in cases:
        repo.save_case(case, stream.order_id)
        memory.record(case, stream)

    return AnalyzeResponse(cases=[c.to_dict() for c in cases])


@router.get("/scenarios")
def list_assurance_scenarios():
    """List the simulator cases available for cross-workflow investigation."""
    return {
        "scenarios": [
            {
                "name": name,
                "expects_violation": info["expects_violation"],
                "violation_type": info["violation_type"],
            }
            for name, info in GROUND_TRUTH.items()
        ]
    }


@router.post("/scenarios/{name}", response_model=AnalyzeResponse)
def analyze_scenario(name: str, db: Session = Depends(get_db)):
    """Run one deterministic simulator scenario through normal analysis."""
    try:
        stream = get_scenario(name)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return analyze(AnalyzeRequest(stream=stream), db=db)


# ---------------------------------------------------------------------------
# Endpoint 3: GET /assurance/cases
# ---------------------------------------------------------------------------

@router.post("/cases", response_model=AnalyzeResponse)
def create_custom_case(request: CreateCaseRequest, db: Session = Depends(get_db)):
    """
    Submit a completely custom event stream.
    If unknown to the deterministic engine, mark as UNKNOWN pattern.
    """
    repo = AssuranceRepository(db)
    memory = OutcomeMemory(repo)
    
    # 1. Parse stream
    events = [FinancialEvent(**e) for e in request.events]
    stream = EventStream(events=events, order_id=request.order_id or f"ord_custom_{uuid.uuid4().hex[:6]}")
    
    # 2. Run canonical deterministic engine
    cases = _engine.investigate(stream)
    
    # 3. Handle unknown pattern
    if not cases:
        # Create an UNKNOWN case
        seq, h = get_canonical_hash(stream)
        case = AssuranceCase(
            workflow="custom",
            pattern_status=PatternStatus.UNKNOWN,
            pattern_hash=h,
            severity="MEDIUM",
            violation_description="Custom stream submitted. Awaiting classification.",
            financial_exposure=int(request.amount_inr * 100),
            order_id=stream.order_id,
            status=AssuranceCaseStatus.OPEN
        )
        
        # Check Pattern Memory for a historical match
        pattern_record = repo.get_pattern_record(h)
        if pattern_record:
            case.pattern_status = PatternStatus.MATCHED
            case.violation_type = ViolationType(pattern_record["classified_violation"])
            case.violation_description = f"Historical Pattern Match: recognized verified pattern"
            # Memory and risk layers will handle the recommendation retrieval automatically
        
        cases = [case]
        
    repo.save_stream(stream)
    for case in cases:
        repo.save_case(case, stream.order_id)
        memory.record(case, stream)
        
    return AnalyzeResponse(cases=[c.to_dict() for c in cases])


@router.post("/cases/{case_id}/classify", response_model=CaseResponse)
def classify_case(case_id: str, body: ClassifyRequest, db: Session = Depends(get_db)):
    """Classify an UNKNOWN case and set its recommended action."""
    repo = AssuranceRepository(db)
    case = repo.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")
        
    if case.pattern_status != PatternStatus.UNKNOWN:
        raise HTTPException(status_code=400, detail="Only UNKNOWN patterns can be manually classified.")
        
    if not body.authorizing_user_id or not body.evidence_event_ids:
        raise HTTPException(status_code=400, detail="Missing cryptographic proof elements (authorizing_user_id, evidence_event_ids).")

    # Update case with human classification
    case.pattern_status = PatternStatus.CLASSIFIED
    case.violation_type = ViolationType(body.violation_type)
    case.recommended_action = RecommendedAction(body.recommended_action)
    case.evidence_event_ids = body.evidence_event_ids
    case.human_classification = {
        "violation_type": body.violation_type,
        "reason": body.reason,
        "recommended_action": body.recommended_action,
        "authorizing_user_id": body.authorizing_user_id,
        "evidence_event_ids": body.evidence_event_ids,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    case.status = AssuranceCaseStatus.PENDING # Ready for resolution
    
    # Save updates
    repo.save_case(case, case.order_id)
    return CaseResponse(case=case.to_dict())


@router.get("/cases")
def list_cases(
    workflow: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db)
):
    """Return all assurance cases in the store."""
    repo = AssuranceRepository(db)
    cases = repo.list_cases(workflow=workflow, severity=severity, status=status)
    return {
        "total": len(cases),
        "cases": [c.to_dict() for c in cases],
    }


@router.get("/metrics")
def metrics(db: Session = Depends(get_db)):
    """Return dashboard totals derived from the current case store."""
    repo = AssuranceRepository(db)
    cases = repo.list_cases()
    actionable = [
        case for case in cases
        if case.violation_type and case.violation_type.value != "UNCERTAIN_PAYMENT_CAPTURED"
    ]
    open_cases = [case for case in actionable if case.status != AssuranceCaseStatus.ASSURED]
    return {
        "open_cases": len(open_cases),
        "exposure": sum(case.financial_exposure for case in open_cases),
        "assured_cases": sum(case.status == AssuranceCaseStatus.ASSURED for case in actionable),
        "total_cases": len(actionable),
    }


# ---------------------------------------------------------------------------
# Endpoint 4: GET /assurance/cases/{case_id}
# ---------------------------------------------------------------------------

@router.get("/cases/{case_id}", response_model=CaseResponse)
def get_case(case_id: str, db: Session = Depends(get_db)):
    """Return a single Assurance Case by ID."""
    repo = AssuranceRepository(db)
    case = repo.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")
    return CaseResponse(case=case.to_dict())


# ---------------------------------------------------------------------------
# Endpoint 5: GET /assurance/cases/{case_id}/timeline
# ---------------------------------------------------------------------------

@router.get("/cases/{case_id}/timeline")
def get_timeline(case_id: str, db: Session = Depends(get_db)):
    """Return the causal chain (timeline) for a case."""
    repo = AssuranceRepository(db)
    case = repo.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")

    stream = repo.get_stream(case.order_id)
    if stream is None:
        raise HTTPException(status_code=409, detail="No event stream is available for this case.")

    return {
        "case_id": case_id,
        "causal_summary": case.causal_summary,
        "steps": [
            {
                "event_id": event.event_id,
                "timestamp": event.timestamp.isoformat(),
                "event_type": event.event_type,
                "description": _event_description(event),
                "payment_id": event.payment_id,
                "amount_inr": event.amount_inr,
            }
            for event in stream.events
        ],
    }


# ---------------------------------------------------------------------------
# Endpoint 6: GET /assurance/cases/{case_id}/graph
# ---------------------------------------------------------------------------

@router.get("/cases/{case_id}/graph")
def get_graph(case_id: str, db: Session = Depends(get_db)):
    repo = AssuranceRepository(db)
    case = repo.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")

    stream = repo.get_stream(case.order_id)
    if stream is None:
        raise HTTPException(status_code=409, detail="No event stream is available for this case.")

    causal_graph = CausalGraphBuilder().build(stream)
    nodes = []
    edges = []

    for i, event in enumerate(stream.events):
        node_id = f"node_{i}"
        nodes.append({
            "id":          node_id,
            "event_id":     event.event_id,
            "event_type":   event.event_type,
            "timestamp":    event.timestamp.isoformat(),
            "description":  _event_description(event),
            "payment_id":   event.payment_id,
            "amount_inr":   event.amount_inr,
            "is_violation_root": event.event_id in case.evidence_event_ids,
        })

    node_ids = {event.event_id: f"node_{i}" for i, event in enumerate(stream.events)}
    for source, target, data in causal_graph.edges(data=True):
        if source in node_ids and target in node_ids:
            relation = data.get("relation", "related")
            edges.append({
                "id": f"edge_{source}_{target}",
                "source": node_ids[source],
                "target": node_ids[target],
                "label": relation,
                "relation": relation,
            })

    return {
        "case_id":  case_id,
        "nodes":    nodes,
        "edges":    edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }


def _event_description(event: FinancialEvent) -> str:
    descriptions = {
        EventType.PAYMENT_CREATED: "Payment initiated",
        EventType.PAYMENT_TIMEOUT: "Gateway timeout — outcome uncertain",
        EventType.AGENT_RETRY_INITIATED: "Autonomous recovery retry initiated",
        EventType.PAYMENT_AUTHORIZED: "Payment authorized by bank",
        EventType.PAYMENT_CAPTURED: "Funds captured",
        EventType.REFUND_REQUESTED: "Refund requested",
        EventType.REFUND_PROCESSED: "Refund processed by gateway",
        EventType.REFUND_COMPLETED: "Refund completed — funds returned",
    }
    return descriptions.get(event.event_type, str(event.event_type))


@router.get("/cases/{case_id}/audit")
def get_audit(case_id: str, db: Session = Depends(get_db)):
    repo = AssuranceRepository(db)
    case = repo.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")
    stream = repo.get_stream(case.order_id)
    if stream is None:
        raise HTTPException(status_code=409, detail="No event stream is available for this case.")

    return {
        "case_id": case_id,
        "entries": [
            {
                "timestamp": event.timestamp.isoformat(),
                "actor": str(getattr(event.source, "value", event.source)).upper(),
                "event_type": event.event_type,
                "description": _event_description(event),
                "event_id": event.event_id,
            }
            for event in stream.events
        ],
    }


@router.get("/cases/{case_id}/explanation")
def get_explanation(case_id: str, db: Session = Depends(get_db)):
    repo = AssuranceRepository(db)
    case = repo.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")
    return {"case_id": case_id, "explanation": explain_case(case).to_dict()}


@router.get("/cases/{case_id}/risk")
def get_risk(case_id: str, db: Session = Depends(get_db)):
    repo = AssuranceRepository(db)
    memory = OutcomeMemory(repo)
    case = repo.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")
    stream = repo.get_stream(case.order_id)
    if not stream:
        raise HTTPException(status_code=404, detail="Stream not found.")
        
    return {"case_id": case_id, "risk": memory.risk_for(case, stream)}


@router.get("/memory")
def get_memory(db: Session = Depends(get_db)):
    repo = AssuranceRepository(db)
    records = repo.get_memory_records()
    return {
        "total_records": len(records),
        "resolved_records": sum(record.resolved for record in records),
        "records": [record.to_dict() for record in records],
    }


# ---------------------------------------------------------------------------
# Endpoint 7: POST /assurance/cases/{case_id}/actions/refund
# ---------------------------------------------------------------------------

@router.post("/cases/{case_id}/actions/refund", response_model=ActionResponse)
def action_refund(case_id: str, body: ActionRequest, db: Session = Depends(get_db)):
    repo = AssuranceRepository(db)
    memory = OutcomeMemory(repo)
    
    case = repo.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")

    if case.recommended_action != RecommendedAction.REFUND_DUPLICATE:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Case '{case_id}' recommends '{case.recommended_action.value if case.recommended_action else None}', "
                f"not REFUND_DUPLICATE. Use the correct action endpoint."
            ),
        )

    if case.status not in (AssuranceCaseStatus.OPEN, AssuranceCaseStatus.PENDING):
        raise HTTPException(
            status_code=409,
            detail=f"Case '{case_id}' is in status '{case.status.value}' — cannot apply refund action.",
        )

    stream = repo.get_stream(case.order_id)
    if stream is None:
        raise HTTPException(status_code=409, detail="No event stream is available for verification.")

    case.status = AssuranceCaseStatus.PENDING
    case.approve_recommendation(note=body.note or "Refund initiated via Assurance API.")

    payment_id = body.payment_id or _default_refund_payment(stream)
    if payment_id is None:
        raise HTTPException(status_code=400, detail="No captured payment is available to refund.")

    refund_amount = case.financial_exposure
    razorpay = RazorpayClient.from_environment()
    provider_refund = None
    if razorpay:
        try:
            provider_refund = razorpay.create_refund(
                payment_id,
                refund_amount,
                notes={"assurance_case_id": case_id, "reason": "duplicate_collection"},
            )
        except RuntimeError as error:
            case.status = AssuranceCaseStatus.PENDING
            repo.save_case(case, stream.order_id)
            raise HTTPException(status_code=502, detail=str(error)) from error

        refund_id = provider_refund.get("id", f"ref_provider_{case_id[2:].lower()}")
        repo.correlate_refund_to_case(refund_id, case_id)
        stream.add(FinancialEvent(
            event_type=EventType.REFUND_REQUESTED,
            timestamp=max(event.timestamp for event in stream.events) + timedelta(seconds=1),
            source=EventSource.ASSURANCE,
            merchant_id=stream.merchant_id,
            order_id=stream.order_id,
            payment_id=payment_id,
            refund_id=refund_id,
            amount=refund_amount,
            caused_by_event_id=case.evidence_event_ids[-1] if case.evidence_event_ids else None,
        ))
        case.outcome_details = {
            "refund_id": refund_id,
            "provider_refund": provider_refund,
            "mode": "razorpay_test",
            "verification": "WAITING_FOR_WEBHOOK",
        }
        case.status = AssuranceCaseStatus.RESOLVING
        repo.save_stream(stream)
        repo.save_case(case, stream.order_id)
        return ActionResponse(case=case.to_dict())

    # Simulation mode
    last_timestamp = max(event.timestamp for event in stream.events)
    refund_id = f"ref_assurance_{case_id[2:].lower()}"
    for event_type, offset in (
        (EventType.REFUND_REQUESTED, 1),
        (EventType.REFUND_PROCESSED, 2),
        (EventType.REFUND_COMPLETED, 3),
    ):
        stream.add(FinancialEvent(
            event_type=event_type,
            timestamp=last_timestamp + timedelta(seconds=offset),
            source=EventSource.ASSURANCE,
            merchant_id=stream.merchant_id,
            order_id=stream.order_id,
            payment_id=payment_id,
            refund_id=refund_id,
            amount=refund_amount,
            caused_by_event_id=case.evidence_event_ids[-1] if case.evidence_event_ids else None,
        ))

    repo.save_stream(stream)
    
    remaining_cases = _engine.investigate(stream)
    duplicate_remaining = next(
        (candidate for candidate in remaining_cases
         if candidate.violation_type == case.violation_type),
        None,
    )
    if duplicate_remaining is None:
        # 1. State Reconstruction
        from app.cases.exposure import ExposureCalculator
        exposure = ExposureCalculator().calculate(case, stream)

        # 2. Expected == Observed
        expected_state = {"action": "recovery", "amount": exposure.gross_exposure, "status": "completed"}
        observed_state = {"action": "recovery", "amount": exposure.verified_recovery, "status": "completed" if exposure.remaining_exposure == 0 else "pending"}

        outcome_payload = {
            "refund_id": refund_id,
            "payment_id": payment_id,
            "provider_refund": provider_refund,
            "mode": "simulation",
            "verification": "financial_resolution",
            "resolution_steps": [
                "APPROVAL", "RESOLVING", "REFUND_REQUESTED",
                "REFUND_PROCESSED", "VERIFYING", "ASSURED",
            ],
            "financial_exposure_eliminated": exposure.verified_recovery,
        }
        
        if not case.exposure_details:
            case.exposure_details = {}
        # Make sure relevant_event_ids is present for the simulated action
        case.exposure_details["relevant_event_ids"] = exposure.relevant_event_ids or ["sim_evt_1"]
        
        # 3. Attempt Verification
        is_verified = case.attempt_verification(
            expected_state, 
            observed_state, 
            outcome_payload,
            provenance_source="simulated_environment",
            provenance_record_id=f"sim_{refund_id}",
            provenance_evidence_ids=[payment_id, refund_id],
            provenance_model_version="v1"
        )
        if is_verified:
            memory.mark_resolved(case, RecommendedAction.REFUND_DUPLICATE.value)
    else:
        case.attempt_verification(
            {"action": "refund", "status": "completed"}, 
            {"action": "refund", "status": "failed"}, 
            {"refund_id": refund_id, "verification": "EXPOSURE_REMAINS"},
            provenance_source="simulated_environment",
            provenance_record_id=f"sim_fail_{refund_id}",
            provenance_evidence_ids=[refund_id],
            provenance_model_version="v1"
        )

    repo.save_case(case, stream.order_id)
    return ActionResponse(case=case.to_dict())


@router.post("/cases/{case_id}/approve", response_model=ActionResponse)
def approve_case(case_id: str, body: ActionRequest, db: Session = Depends(get_db)):
    repo = AssuranceRepository(db)
    case = repo.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")
    if case.status not in (AssuranceCaseStatus.OPEN, AssuranceCaseStatus.PENDING):
        raise HTTPException(status_code=409, detail=f"Case '{case_id}' is not OPEN or PENDING.")
    case.status = AssuranceCaseStatus.PENDING
    case.resolution_note = body.note or "Recommendation approved via Assurance API."
    
    repo.save_case(case, case.order_id)
    return ActionResponse(case=case.to_dict())


@router.get("/cases/{case_id}/recommendation")
def get_case_recommendation(case_id: str, db: Session = Depends(get_db)):
    from app.learning.paths import RecommendationEngine
    repo = AssuranceRepository(db)
    case = repo.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")
        
    engine = RecommendationEngine(repo)
    return engine.recommend(case)


@router.get("/cases/{case_id}/memory")
def get_case_memory(case_id: str, db: Session = Depends(get_db)):
    repo = AssuranceRepository(db)
    case = repo.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")
        
    records = repo.get_memory_records()
    similar = [
        r.to_dict() for r in records
        if case.violation_type and r.violation_type == case.violation_type.value
        and r.case_id != case.case_id
    ]
    return {"historical_records": similar}


def _default_refund_payment(stream: EventStream) -> str | None:
    agent_created = [
        event.payment_id for event in stream.events
        if event.event_type == EventType.PAYMENT_CREATED
        and event.source == EventSource.AGENT
        and event.payment_id
    ]
    if agent_created:
        return agent_created[-1]
    captured = [
        event.payment_id for event in stream.events
        if event.event_type == EventType.PAYMENT_CAPTURED and event.payment_id
    ]
    return captured[-1] if captured else None
