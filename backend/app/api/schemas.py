from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field

from app.models.event import EventStream, FinancialEvent


class AnalyzeRequest(BaseModel):
    stream: EventStream


class AnalyzeResponse(BaseModel):
    cases: list[dict[str, Any]]


class CaseResponse(BaseModel):
    case: dict[str, Any]


class ActionRequest(BaseModel):
    payment_id: Optional[str] = None
    note: str = ""


class ActionResponse(BaseModel):
    case: dict[str, Any]


class CreateCaseRequest(BaseModel):
    name: str
    amount_inr: float
    events: list[FinancialEvent]
    order_id: Optional[str] = None
    currency: str = "INR"


class ClassifyRequest(BaseModel):
    violation_type: str
    reason: str
    recommended_action: str
    authorizing_user_id: str
    evidence_event_ids: list[str]
