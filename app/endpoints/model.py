# app/endpoints/model.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database.session import get_db
from crud import model as crud
from schemas.model import ModelUpdate, ModelResponse, MetricsUpdateIn

router = APIRouter(prefix="/model", tags=["Model"])

@router.get("", response_model=ModelResponse)
def get_model(db: Session = Depends(get_db)):
    obj = crud.get_single(db)
    if not obj:
        raise HTTPException(404, "no model")
    return obj

@router.put("", response_model=ModelResponse)
def update_model(payload: ModelUpdate, db: Session = Depends(get_db)):
    obj = crud.update_single(db, payload.model_dump(exclude_unset=True))
    return obj


@router.put("/metrics", response_model=ModelResponse)
def update_metrics(payload: MetricsUpdateIn, db: Session = Depends(get_db)):
    obj = crud.update_metrics(
        db,
        accuracy=payload.accuracy,
        avg_response_time_ms=payload.avg_response_time_ms,
        month_conversations=payload.month_conversations,
        uptime_percent=payload.uptime_percent,
    )
    if not obj:
        raise HTTPException(404, "no model")
    return obj
