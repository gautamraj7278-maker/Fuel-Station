from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app import models, schemas
from app.routers.auth import require_admin

router = APIRouter()

@router.post("/", response_model=schemas.Dispenser, status_code=status.HTTP_201_CREATED)
def create_pump(
    pump: schemas.DispenserCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    """Legacy alias (/api/pumps): create a new dispenser."""
    existing = db.query(models.Dispenser).filter(
        models.Dispenser.dispenser_number == pump.dispenser_number
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Dispenser number already exists")

    db_pump = models.Dispenser(
        dispenser_number=pump.dispenser_number,
        fuel_type="petrol",
        is_active=pump.is_active,
    )
    db.add(db_pump)
    db.commit()
    db.refresh(db_pump)
    return db_pump

@router.get("/", response_model=List[schemas.Dispenser])
def get_pumps(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    """Legacy alias: list dispensers."""
    pumps = db.query(models.Dispenser).all()
    return pumps

@router.get("/{pump_id}", response_model=schemas.Dispenser)
def get_pump(
    pump_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    """Legacy alias: get a specific dispenser by ID."""
    pump = db.query(models.Dispenser).filter(models.Dispenser.id == pump_id).first()
    if not pump:
        raise HTTPException(status_code=404, detail="Dispenser not found")
    return pump

@router.put("/{pump_id}", response_model=schemas.Dispenser)
def update_pump(
    pump_id: int,
    pump_update: schemas.DispenserUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    """Legacy alias: update a dispenser."""
    pump = db.query(models.Dispenser).filter(models.Dispenser.id == pump_id).first()
    if not pump:
        raise HTTPException(status_code=404, detail="Dispenser not found")
    
    update_data = pump_update.dict(exclude_unset=True)
    if "dispenser_number" in update_data:
        existing = (
            db.query(models.Dispenser)
            .filter(models.Dispenser.dispenser_number == update_data["dispenser_number"])
            .first()
        )
        if existing and existing.id != pump_id:
            raise HTTPException(status_code=400, detail="Dispenser number already exists")

    for field, value in update_data.items():
        setattr(pump, field, value)
    
    db.commit()
    db.refresh(pump)
    return pump

@router.delete("/{pump_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pump(
    pump_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    """Legacy alias: delete a dispenser."""
    pump = db.query(models.Dispenser).filter(models.Dispenser.id == pump_id).first()
    if not pump:
        raise HTTPException(status_code=404, detail="Dispenser not found")
    
    if db.query(models.Sale).filter(models.Sale.dispenser_id == pump_id).first():
        raise HTTPException(
            status_code=400,
            detail="Cannot delete dispenser because sales exist for it. Deactivate it instead.",
        )
    if db.query(models.DispenserShiftAssignment).filter(models.DispenserShiftAssignment.dispenser_id == pump_id).first():
        raise HTTPException(
            status_code=400,
            detail="Cannot delete dispenser because shift assignments exist for it. Deactivate it instead.",
        )

    try:
        nozzle_ids = [n_id for (n_id,) in db.query(models.Nozzle.id).filter(models.Nozzle.dispenser_id == pump_id).all()]
        if nozzle_ids:
            db.query(models.Meter).filter(models.Meter.nozzle_id.in_(nozzle_ids)).delete(synchronize_session=False)
            db.query(models.Nozzle).filter(models.Nozzle.id.in_(nozzle_ids)).delete(synchronize_session=False)

        db.delete(pump)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Cannot delete dispenser because it is referenced by other records.",
        )
    return None
