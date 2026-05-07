from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from app.database import get_db
from app import models, schemas
from app.routers.auth import require_admin

router = APIRouter()


def resolve_shift_for_datetime(db: Session, dt: datetime) -> tuple[models.ShiftCode, datetime.date]:
    configs = db.query(models.ShiftConfig).filter(models.ShiftConfig.is_active == True).all()  # noqa: E712
    if not configs:
        return (models.ShiftCode.A, dt.date())

    t = dt.time()

    for cfg in configs:
        start = cfg.start_time
        end = cfg.end_time
        if start == end:
            continue

        if start < end:
            if start <= t < end:
                return (cfg.shift, dt.date())
        else:
            # wraps midnight
            if t >= start or t < end:
                business_date = dt.date() if t >= start else (dt.date())
                if t < end:
                    business_date = dt.date()  # already next calendar day, but business date is previous
                    business_date = business_date.fromordinal(business_date.toordinal() - 1)
                return (cfg.shift, business_date)

    return (models.ShiftCode.A, dt.date())


@router.post("/", response_model=schemas.ShiftConfig, status_code=status.HTTP_201_CREATED)
def upsert_shift_config(
    payload: schemas.ShiftConfigCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    existing = db.query(models.ShiftConfig).filter(models.ShiftConfig.shift == payload.shift).first()
    if existing:
        existing.start_time = payload.start_time
        existing.end_time = payload.end_time
        existing.is_active = payload.is_active
        existing.remarks = payload.remarks
        db.commit()
        db.refresh(existing)
        return existing

    cfg = models.ShiftConfig(**payload.dict())
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


@router.get("/", response_model=List[schemas.ShiftConfig])
def list_shift_configs(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    return db.query(models.ShiftConfig).order_by(models.ShiftConfig.shift.asc()).all()


@router.put("/{shift}", response_model=schemas.ShiftConfig)
def update_shift_config(
    shift: schemas.ShiftCode,
    payload: schemas.ShiftConfigUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    cfg = db.query(models.ShiftConfig).filter(models.ShiftConfig.shift == models.ShiftCode(shift.value)).first()
    if not cfg:
        raise HTTPException(status_code=404, detail="Shift config not found")

    data = payload.dict(exclude_unset=True)
    for k, v in data.items():
        setattr(cfg, k, v)

    db.commit()
    db.refresh(cfg)
    return cfg


@router.get("/current")
def get_current_shift(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    shift, business_date = resolve_shift_for_datetime(db, datetime.utcnow())
    return {"shift": shift.value, "business_date": business_date.isoformat()}
