from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.db.database import get_db
from app.learning.training import TrainingService, InsufficientDataError

router = APIRouter()

class LearningStatusResponse(BaseModel):
    status: str
    verified_outcomes: int
    verified_patterns: int
    ml_training_examples: int
    active_version: str
    pending_model: Optional[dict] = None

class TrainResponse(BaseModel):
    version: str
    status: str
    f1: float
    precision: float
    recall: float

@router.get("/status", response_model=LearningStatusResponse)
def get_status(db: Session = Depends(get_db)):
    svc = TrainingService(db)
    return svc.get_learning_status()

@router.post("/train", response_model=TrainResponse)
def train_model(db: Session = Depends(get_db)):
    svc = TrainingService(db)
    try:
        res = svc.train_candidate_model()
        return res
    except InsufficientDataError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/models/{version}/promote")
def promote_model(version: str, db: Session = Depends(get_db)):
    svc = TrainingService(db)
    try:
        svc.promote_model(version)
        return {"status": "success", "active_version": version}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
