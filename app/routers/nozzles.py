from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app import models, schemas
from app.routers.auth import require_admin

router = APIRouter()


@router.post("/", response_model=schemas.Nozzle, status_code=status.HTTP_201_CREATED)
def create_nozzle(
    nozzle: schemas.NozzleCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    dispenser = db.query(models.Dispenser).filter(models.Dispenser.id == nozzle.dispenser_id).first()
    if not dispenser:
        raise HTTPException(status_code=404, detail="Dispenser not found")
    
    if nozzle.product_id is None:
        raise HTTPException(status_code=400, detail="product_id is required")
    if nozzle.tank_id is None:
        raise HTTPException(status_code=400, detail="tank_id is required")
    
    product = db.query(models.Product).filter(models.Product.id == nozzle.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    tank = db.query(models.Tank).filter(models.Tank.id == nozzle.tank_id).first()
    if not tank:
        raise HTTPException(status_code=404, detail="Tank not found")
    
    if tank.product_id != product.id:
        raise HTTPException(status_code=400, detail="Tank product does not match nozzle product")

    existing = (
        db.query(models.Nozzle)
        .filter(models.Nozzle.dispenser_id == nozzle.dispenser_id)
        .filter(models.Nozzle.nozzle_number == nozzle.nozzle_number)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Nozzle number already exists for this dispenser")

    # Keep legacy fuel_type aligned to product for inventory/reporting.
    db_nozzle = models.Nozzle(
        dispenser_id=nozzle.dispenser_id,
        nozzle_number=nozzle.nozzle_number,
        fuel_type=product.fuel_type,
        product_id=product.id,
        tank_id=tank.id,
        is_active=nozzle.is_active,
    )
    db.add(db_nozzle)
    db.commit()
    db.refresh(db_nozzle)
    return db_nozzle


@router.get("/", response_model=List[schemas.Nozzle])
def list_nozzles(
    dispenser_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    query = (
        db.query(models.Nozzle)
        .join(models.Dispenser, models.Nozzle.dispenser_id == models.Dispenser.id)
        .filter(models.Nozzle.is_deleted == False, models.Dispenser.is_deleted == False)  # noqa: E712
    )
    if dispenser_id is not None:
        query = query.filter(models.Nozzle.dispenser_id == dispenser_id)
    return query.order_by(models.Nozzle.dispenser_id.asc(), models.Nozzle.nozzle_number.asc()).all()


@router.get("/deleted", response_model=List[schemas.DeletedItem])
def list_deleted_nozzles(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    rows = (
        db.query(models.Nozzle)
        .filter(models.Nozzle.is_deleted == True)  # noqa: E712
        .order_by(models.Nozzle.deleted_at.desc(), models.Nozzle.id.desc())
        .all()
    )
    return [
        schemas.DeletedItem(
            id=r.id,
            label=f"Nozzle {r.nozzle_number} (Dispenser {r.dispenser_id})",
            deleted_at=r.deleted_at,
            deleted_by_user_id=r.deleted_by_user_id,
            deleted_by_username=(r.deleted_by.username if r.deleted_by else None),
        )
        for r in rows
    ]


@router.post("/deleted/{nozzle_id}/restore", response_model=schemas.Nozzle)
def restore_nozzle(
    nozzle_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    nozzle = (
        db.query(models.Nozzle)
        .filter(models.Nozzle.id == nozzle_id, models.Nozzle.is_deleted == True)  # noqa: E712
        .first()
    )
    if not nozzle:
        raise HTTPException(status_code=404, detail="Deleted nozzle not found")

    nozzle.is_deleted = False
    nozzle.deleted_at = None
    nozzle.deleted_by_user_id = None
    db.commit()
    db.refresh(nozzle)
    return nozzle


@router.delete("/deleted/{nozzle_id}", status_code=status.HTTP_204_NO_CONTENT)
def purge_deleted_nozzle(
    nozzle_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    nozzle = (
        db.query(models.Nozzle)
        .filter(models.Nozzle.id == nozzle_id, models.Nozzle.is_deleted == True)  # noqa: E712
        .first()
    )
    if not nozzle:
        raise HTTPException(status_code=404, detail="Deleted nozzle not found")

    try:
        db.query(models.Meter).filter(models.Meter.nozzle_id == nozzle_id).delete(synchronize_session=False)
        db.delete(nozzle)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Cannot purge nozzle because it is referenced by other records")
    return None


@router.put("/{nozzle_id}", response_model=schemas.Nozzle)
def update_nozzle(
    nozzle_id: int,
    nozzle_update: schemas.NozzleUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    nozzle = (
        db.query(models.Nozzle)
        .filter(models.Nozzle.id == nozzle_id, models.Nozzle.is_deleted == False)  # noqa: E712
        .first()
    )
    if not nozzle:
        raise HTTPException(status_code=404, detail="Nozzle not found")

    update_data = nozzle_update.dict(exclude_unset=True)

    # If updating product or tank, validate mapping and align fuel_type
    new_product_id = update_data.get("product_id", nozzle.product_id)
    new_tank_id = update_data.get("tank_id", nozzle.tank_id)

    if new_product_id is not None:
        product = db.query(models.Product).filter(models.Product.id == new_product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        update_data["fuel_type"] = product.fuel_type

        if new_tank_id is not None:
            tank = db.query(models.Tank).filter(models.Tank.id == new_tank_id).first()
            if not tank:
                raise HTTPException(status_code=404, detail="Tank not found")
            if tank.product_id != product.id:
                raise HTTPException(status_code=400, detail="Tank product does not match nozzle product")

    for field, value in update_data.items():
        setattr(nozzle, field, value)

    db.commit()
    db.refresh(nozzle)
    return nozzle


@router.delete("/{nozzle_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_nozzle(
    nozzle_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    nozzle = (
        db.query(models.Nozzle)
        .filter(models.Nozzle.id == nozzle_id, models.Nozzle.is_deleted == False)  # noqa: E712
        .first()
    )
    if not nozzle:
        raise HTTPException(status_code=404, detail="Nozzle not found")

    if db.query(models.Sale).filter(models.Sale.nozzle_id == nozzle_id).first():
        raise HTTPException(
            status_code=400,
            detail="Cannot delete nozzle because sales exist for it. Deactivate it instead.",
        )

    nozzle.is_deleted = True
    nozzle.deleted_at = datetime.utcnow()
    nozzle.deleted_by_user_id = current_user.id
    db.query(models.Meter).filter(models.Meter.nozzle_id == nozzle_id).update(
        {
            models.Meter.is_deleted: True,
            models.Meter.deleted_at: nozzle.deleted_at,
            models.Meter.deleted_by_user_id: current_user.id,
        },
        synchronize_session=False,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Cannot delete nozzle because it is referenced by other records.",
        )
    return None
