from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app import models, schemas
from app.routers.auth import require_admin

router = APIRouter()


@router.post("/", response_model=schemas.Dispenser, status_code=status.HTTP_201_CREATED)
def create_dispenser(
    dispenser: schemas.DispenserCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """Create a new dispenser"""
    existing = (
        db.query(models.Dispenser)
        .filter(models.Dispenser.dispenser_number == dispenser.dispenser_number)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Dispenser number already exists")

    # Dispenser is product-agnostic; product is tied to nozzle. Keep a placeholder fuel_type for legacy DB column.
    db_dispenser = models.Dispenser(
        dispenser_number=dispenser.dispenser_number,
        fuel_type="petrol",
        is_active=dispenser.is_active,
    )
    db.add(db_dispenser)
    db.commit()
    db.refresh(db_dispenser)
    return db_dispenser


@router.get("/", response_model=List[schemas.Dispenser])
def list_dispensers(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """List all dispensers"""
    return (
        db.query(models.Dispenser)
        .filter(models.Dispenser.is_deleted == False)  # noqa: E712
        .all()
    )


@router.get("/deleted", response_model=List[schemas.DeletedItem])
def list_deleted_dispensers(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    rows = (
        db.query(models.Dispenser)
        .filter(models.Dispenser.is_deleted == True)  # noqa: E712
        .order_by(models.Dispenser.deleted_at.desc(), models.Dispenser.id.desc())
        .all()
    )
    return [
        schemas.DeletedItem(
            id=r.id,
            label=r.dispenser_number,
            deleted_at=r.deleted_at,
            deleted_by_user_id=r.deleted_by_user_id,
            deleted_by_username=(r.deleted_by.username if r.deleted_by else None),
        )
        for r in rows
    ]


@router.post("/deleted/{dispenser_id}/restore", response_model=schemas.Dispenser)
def restore_dispenser(
    dispenser_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    dispenser = (
        db.query(models.Dispenser)
        .filter(models.Dispenser.id == dispenser_id, models.Dispenser.is_deleted == True)  # noqa: E712
        .first()
    )
    if not dispenser:
        raise HTTPException(status_code=404, detail="Deleted dispenser not found")

    dispenser.is_deleted = False
    dispenser.deleted_at = None
    dispenser.deleted_by_user_id = None
    db.commit()
    db.refresh(dispenser)
    return dispenser


@router.delete("/deleted/{dispenser_id}", status_code=status.HTTP_204_NO_CONTENT)
def purge_deleted_dispenser(
    dispenser_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    dispenser = (
        db.query(models.Dispenser)
        .filter(models.Dispenser.id == dispenser_id, models.Dispenser.is_deleted == True)  # noqa: E712
        .first()
    )
    if not dispenser:
        raise HTTPException(status_code=404, detail="Deleted dispenser not found")

    nozzle_ids = [n_id for (n_id,) in db.query(models.Nozzle.id).filter(models.Nozzle.dispenser_id == dispenser_id).all()]
    try:
        if nozzle_ids:
            db.query(models.Meter).filter(models.Meter.nozzle_id.in_(nozzle_ids)).delete(synchronize_session=False)
            db.query(models.Nozzle).filter(models.Nozzle.id.in_(nozzle_ids)).delete(synchronize_session=False)
        db.delete(dispenser)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Cannot purge dispenser because it is referenced by other records")
    return None


@router.get("/{dispenser_id}", response_model=schemas.Dispenser)
def get_dispenser(
    dispenser_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    dispenser = (
        db.query(models.Dispenser)
        .filter(models.Dispenser.id == dispenser_id, models.Dispenser.is_deleted == False)  # noqa: E712
        .first()
    )
    if not dispenser:
        raise HTTPException(status_code=404, detail="Dispenser not found")
    return dispenser


@router.put("/{dispenser_id}", response_model=schemas.Dispenser)
def update_dispenser(
    dispenser_id: int,
    payload: schemas.DispenserUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    dispenser = (
        db.query(models.Dispenser)
        .filter(models.Dispenser.id == dispenser_id, models.Dispenser.is_deleted == False)  # noqa: E712
        .first()
    )
    if not dispenser:
        raise HTTPException(status_code=404, detail="Dispenser not found")

    update_data = payload.dict(exclude_unset=True)

    if "dispenser_number" in update_data:
        existing = (
            db.query(models.Dispenser)
            .filter(models.Dispenser.dispenser_number == update_data["dispenser_number"])
            .first()
        )
        if existing and existing.id != dispenser_id:
            raise HTTPException(status_code=400, detail="Dispenser number already exists")

    for field, value in update_data.items():
        setattr(dispenser, field, value)

    db.commit()
    db.refresh(dispenser)
    return dispenser


@router.delete("/{dispenser_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dispenser(
    dispenser_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    dispenser = (
        db.query(models.Dispenser)
        .filter(models.Dispenser.id == dispenser_id, models.Dispenser.is_deleted == False)  # noqa: E712
        .first()
    )
    if not dispenser:
        raise HTTPException(status_code=404, detail="Dispenser not found")

    # Prevent deleting dispensers that are referenced by immutable operational records.
    if db.query(models.Sale).filter(models.Sale.dispenser_id == dispenser_id).first():
        raise HTTPException(
            status_code=400,
            detail="Cannot delete dispenser because sales exist for it. Deactivate it instead.",
        )
    if db.query(models.DispenserShiftAssignment).filter(models.DispenserShiftAssignment.dispenser_id == dispenser_id).first():
        raise HTTPException(
            status_code=400,
            detail="Cannot delete dispenser because shift assignments exist for it. Deactivate it instead.",
        )

    try:
        dispenser.is_deleted = True
        dispenser.deleted_at = datetime.utcnow()
        dispenser.deleted_by_user_id = current_user.id
        nozzle_ids = [n_id for (n_id,) in db.query(models.Nozzle.id).filter(models.Nozzle.dispenser_id == dispenser_id).all()]
        if nozzle_ids:
            db.query(models.Nozzle).filter(models.Nozzle.id.in_(nozzle_ids)).update(
                {
                    models.Nozzle.is_deleted: True,
                    models.Nozzle.deleted_at: dispenser.deleted_at,
                    models.Nozzle.deleted_by_user_id: current_user.id,
                },
                synchronize_session=False,
            )
            db.query(models.Meter).filter(models.Meter.nozzle_id.in_(nozzle_ids)).update(
                {
                    models.Meter.is_deleted: True,
                    models.Meter.deleted_at: dispenser.deleted_at,
                    models.Meter.deleted_by_user_id: current_user.id,
                },
                synchronize_session=False,
            )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Cannot delete dispenser because it is referenced by other records.",
        )
    return None
