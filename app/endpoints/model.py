# FastAPI 라우터

from __future__ import annotations
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.session import get_db
from crud import model as crud
from schemas.model import ModelCreate, ModelUpdate, ModelResponse

router = APIRouter(prefix="/models", tags=["Model"])

OrderBy = Literal["recent", "accuracy", "uptime", "speed", "conversations"]

@router.post("/", response_model=ModelResponse, status_code=status.HTTP_201_CREATED)
def create_model(payload: ModelCreate, db: Session = Depends(get_db)):
    return crud.create(db, payload.dict())


@router.get("/active", response_model=ModelResponse)
def get_active_model(db: Session = Depends(get_db)):
    obj = crud.get_active(db)
    if not obj:
        raise HTTPException(status_code=404, detail="active model not set")
    return obj


@router.get("/", response_model=list[ModelResponse])
def list_models(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    provider_name: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    q: Optional[str] = Query(None, description="search in name/description"),
    order_by: OrderBy = Query("recent", pattern="^(recent|accuracy|uptime|speed|conversations)$"),
    db: Session = Depends(get_db),
):
    return crud.list_models(
        db,
        offset=offset,
        limit=limit,
        provider_name=provider_name,
        is_active=is_active,
        q=q,
        order_by=order_by,  # type: ignore[arg-type]
    )



@router.get("/{model_id}", response_model=ModelResponse)
def get_model(model_id: int, db: Session = Depends(get_db)):
    obj = crud.get(db, model_id)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.patch("/{model_id}", response_model=ModelResponse)
def update_model(model_id: int, payload: ModelUpdate, db: Session = Depends(get_db)):
    obj = crud.update(db, model_id, payload.dict(exclude_unset=True))
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_model(model_id: int, db: Session = Depends(get_db)):
    if not crud.delete(db, model_id):
        raise HTTPException(status_code=404, detail="not found")
    return None


@router.patch("/{model_id}/activate", response_model=ModelResponse)
def activate_model(model_id: int, db: Session = Depends(get_db)):
    obj = crud.set_active(db, model_id)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.patch("/{model_id}/deactivate", response_model=ModelResponse)
def deactivate_model(model_id: int, db: Session = Depends(get_db)):
    obj = crud.deactivate(db, model_id)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


class MetricsUpdateIn(BaseModel):
    accuracy: Optional[float] = Field(default=None, ge=0, le=100)
    avg_response_time_ms: Optional[int] = Field(default=None, ge=0)
    month_conversations: Optional[int] = Field(default=None, ge=0)
    uptime_percent: Optional[float] = Field(default=None, ge=0, le=100)
    status_text: Optional[str] = None


@router.put("/{model_id}/metrics", response_model=ModelResponse)
def update_metrics(model_id: int, payload: MetricsUpdateIn, db: Session = Depends(get_db)):
    obj = crud.update_metrics(
        db,
        model_id,
        accuracy=payload.accuracy,
        avg_response_time_ms=payload.avg_response_time_ms,
        month_conversations=payload.month_conversations,
        uptime_percent=payload.uptime_percent,
        status_text=payload.status_text,
    )
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj
