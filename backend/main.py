"""
Assurance — FastAPI Entry Point
-------------------------------
Starts the Assurance engine as a REST API.

Endpoints:
  POST /investigate      — Submit an EventStream, get AssuranceCases back
  GET  /scenarios        — List available demo scenarios
  GET  /scenarios/{name} — Run a named scenario and return results
  GET  /health           — Health check
"""

from __future__ import annotations

import sys
import os

# Allow imports from backend root
sys.path.insert(0, os.path.dirname(__file__) + "/..")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any

from app.db.database import engine, Base
from app.db import models  # ensure models are imported to be registered with Base

# Create tables
Base.metadata.create_all(bind=engine)

from app.engine import AssuranceEngine
from app.models.event import EventStream, FinancialEvent
from app.api.routes import router as assurance_router, webhook_router
from app.api.learning import router as learning_router
from simulator.scenarios import get_scenario, GROUND_TRUTH

app = FastAPI(
    title="Assurance",
    description="Financial State Verification Engine — Razorpay Hackathon 2026",
    version="0.1.0",
)

# Allow the React frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = AssuranceEngine()

# Mount the structured assurance router
app.include_router(assurance_router)
app.include_router(webhook_router)
app.include_router(learning_router, prefix="/assurance/learning", tags=["Learning"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class InvestigateRequest(BaseModel):
    order_id:    str | None = None
    merchant_id: str | None = None
    events:      list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "system": "Assurance Financial Verification Engine"}


@app.get("/scenarios")
def list_scenarios():
    """List all available demo scenarios with their ground truth."""
    return {
        "scenarios": [
            {
                "name":             name,
                "expects_violation": info["expects_violation"],
                "violation_type":    info["violation_type"],
            }
            for name, info in GROUND_TRUTH.items()
        ]
    }


@app.get("/scenarios/{name}")
def run_scenario(name: str):
    """
    Run a named scenario through Assurance and return the results.
    This is the primary demo endpoint.
    """
    try:
        stream = get_scenario(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    cases = engine.investigate(stream)

    return {
        "scenario":       name,
        "event_count":    len(stream),
        "payment_ids":    stream.payment_ids,
        "cases_detected": len(cases),
        "assured":        len(cases) == 0,
        "cases":          [c.to_dict() for c in cases],
        "events":         [
            {
                "event_id":   e.event_id,
                "event_type": e.event_type,
                "timestamp":  e.timestamp.isoformat(),
                "source":     e.source,
                "payment_id": e.payment_id,
                "amount_inr": e.amount_inr,
            }
            for e in stream.events
        ],
    }


@app.post("/investigate")
def investigate(req: InvestigateRequest):
    """
    Submit raw events and get AssuranceCases back.
    The frontend uses this to POST custom event streams.
    """
    stream = EventStream(order_id=req.order_id, merchant_id=req.merchant_id)

    for evt_data in req.events:
        try:
            event = FinancialEvent(**evt_data)
            stream.add(event)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Invalid event: {e}")

    cases = engine.investigate(stream)

    return {
        "event_count":    len(stream),
        "cases_detected": len(cases),
        "assured":        len(cases) == 0,
        "cases":          [c.to_dict() for c in cases],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
