from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app import models, schemas
from app.routers.auth import require_admin

router = APIRouter()


@router.post("/", response_model=schemas.Meter, status_code=status.HTTP_201_CREATED)
def create_meter(
    meter: schemas.MeterCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    nozzle = db.query(models.Nozzle).filter(models.Nozzle.id == meter.nozzle_id).first()
    if not nozzle:
        raise HTTPException(status_code=404, detail="Nozzle not found")

    db_meter = models.Meter(**meter.dict())
    db.add(db_meter)
    db.commit()
    db.refresh(db_meter)
    return db_meter


@router.get("/", response_model=List[schemas.Meter])
def list_meters(
    nozzle_id: Optional[int] = None,
    dispenser_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    query = (
        db.query(models.Meter)
        .join(models.Nozzle, models.Meter.nozzle_id == models.Nozzle.id)
        .filter(models.Meter.is_deleted == False, models.Nozzle.is_deleted == False)  # noqa: E712
    )

    if nozzle_id is not None:
        query = query.filter(models.Meter.nozzle_id == nozzle_id)

    if dispenser_id is not None:
        # meters -> nozzle -> dispenser
        query = query.join(models.Nozzle).filter(models.Nozzle.dispenser_id == dispenser_id)

    return query.order_by(models.Meter.nozzle_id.asc(), models.Meter.meter_name.asc()).all()


@router.get("/deleted", response_model=List[schemas.DeletedItem])
def list_deleted_meters(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    rows = (
        db.query(models.Meter)
        .filter(models.Meter.is_deleted == True)  # noqa: E712
        .order_by(models.Meter.deleted_at.desc(), models.Meter.id.desc())
        .all()
    )
    return [
        schemas.DeletedItem(
            id=r.id,
            label=f"{r.meter_name} (Nozzle {r.nozzle_id})",
            deleted_at=r.deleted_at,
            deleted_by_user_id=r.deleted_by_user_id,
            deleted_by_username=(r.deleted_by.username if r.deleted_by else None),
        )
        for r in rows
    ]


@router.post("/deleted/{meter_id}/restore", response_model=schemas.Meter)
def restore_meter(
    meter_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    meter = (
        db.query(models.Meter)
        .filter(models.Meter.id == meter_id, models.Meter.is_deleted == True)  # noqa: E712
        .first()
    )
    if not meter:
        raise HTTPException(status_code=404, detail="Deleted meter not found")

    meter.is_deleted = False
    meter.deleted_at = None
    meter.deleted_by_user_id = None
    db.commit()
    db.refresh(meter)
    return meter


@router.delete("/deleted/{meter_id}", status_code=status.HTTP_204_NO_CONTENT)
def purge_deleted_meter(
    meter_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    meter = (
        db.query(models.Meter)
        .filter(models.Meter.id == meter_id, models.Meter.is_deleted == True)  # noqa: E712
        .first()
    )
    if not meter:
        raise HTTPException(status_code=404, detail="Deleted meter not found")

    try:
        db.delete(meter)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Cannot purge meter because it is referenced by other records")
    return None


@router.get("/{meter_id}", response_model=schemas.Meter)
def get_meter(
    meter_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    meter = (
        db.query(models.Meter)
        .filter(models.Meter.id == meter_id, models.Meter.is_deleted == False)  # noqa: E712
        .first()
    )
    if not meter:
        raise HTTPException(status_code=404, detail="Meter not found")
    return meter


@router.get("/{meter_id}/next-opening")
def get_next_opening(
    meter_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    meter = (
        db.query(models.Meter)
        .filter(models.Meter.id == meter_id, models.Meter.is_deleted == False)  # noqa: E712
        .first()
    )
    if not meter:
        raise HTTPException(status_code=404, detail="Meter not found")

    nozzle = db.query(models.Nozzle).filter(models.Nozzle.id == meter.nozzle_id).first()

    return {
        "meter_id": meter.id,
        "nozzle_id": meter.nozzle_id,
        "dispenser_id": nozzle.dispenser_id if nozzle else None,
        "fuel_type": nozzle.fuel_type if nozzle else None,
        "max_value": meter.max_value,
        "next_opening": meter.last_reading,
    }


@router.put("/{meter_id}", response_model=schemas.Meter)
def update_meter(
    meter_id: int,
    payload: schemas.MeterUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    meter = (
        db.query(models.Meter)
        .filter(models.Meter.id == meter_id, models.Meter.is_deleted == False)  # noqa: E712
        .first()
    )
    if not meter:
        raise HTTPException(status_code=404, detail="Meter not found")

    update_data = payload.dict(exclude_unset=True)
    # None max_value means "no wrap"; allow explicit None by using exclude_unset only.
    for field, value in update_data.items():
        setattr(meter, field, value)

    db.commit()
    db.refresh(meter)
    return meter


@router.delete("/{meter_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meter(
    meter_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    meter = db.query(models.Meter).filter(models.Meter.id == meter_id).first()
    if not meter:
        raise HTTPException(status_code=404, detail="Meter not found")

    if db.query(models.Sale).filter(models.Sale.meter_id == meter_id).first():
        raise HTTPException(
            status_code=400,
            detail="Cannot delete meter because sales exist for it. Deactivate it instead.",
        )

    meter.is_deleted = True
    meter.deleted_at = datetime.utcnow()
    meter.deleted_by_user_id = current_user.id
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Cannot delete meter because it is referenced by other records.",
        )
    return None
