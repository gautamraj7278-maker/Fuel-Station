from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app import models, schemas
from app.routers.auth import require_admin

router = APIRouter()


@router.get("/", response_model=List[schemas.Designation])
def list_designations(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    return (
        db.query(models.Designation)
        .filter(models.Designation.is_deleted == False)  # noqa: E712
        .order_by(models.Designation.name.asc())
        .all()
    )


@router.get("/deleted", response_model=List[schemas.DeletedItem])
def list_deleted_designations(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    rows = (
        db.query(models.Designation)
        .filter(models.Designation.is_deleted == True)  # noqa: E712
        .order_by(models.Designation.deleted_at.desc(), models.Designation.id.desc())
        .all()
    )
    return [
        schemas.DeletedItem(
            id=r.id,
            label=r.name,
            deleted_at=r.deleted_at,
            deleted_by_user_id=r.deleted_by_user_id,
            deleted_by_username=(r.deleted_by.username if r.deleted_by else None),
        )
        for r in rows
    ]


@router.post("/deleted/{designation_id}/restore", response_model=schemas.Designation)
def restore_designation(
    designation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    d = (
        db.query(models.Designation)
        .filter(models.Designation.id == designation_id, models.Designation.is_deleted == True)  # noqa: E712
        .first()
    )
    if not d:
        raise HTTPException(status_code=404, detail="Deleted designation not found")

    d.is_deleted = False
    d.deleted_at = None
    d.deleted_by_user_id = None
    db.commit()
    db.refresh(d)
    return d


@router.delete("/deleted/{designation_id}", status_code=status.HTTP_204_NO_CONTENT)
def purge_deleted_designation(
    designation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    designation = (
        db.query(models.Designation)
        .filter(models.Designation.id == designation_id, models.Designation.is_deleted == True)  # noqa: E712
        .first()
    )
    if not designation:
        raise HTTPException(status_code=404, detail="Deleted designation not found")

    try:
        db.delete(designation)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Cannot purge designation because it is referenced by other records")
    return None


@router.post("/", response_model=schemas.Designation, status_code=status.HTTP_201_CREATED)
def create_designation(
    payload: schemas.DesignationCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    existing = db.query(models.Designation).filter(models.Designation.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Designation already exists")

    d = models.Designation(name=payload.name, is_active=payload.is_active)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


@router.put("/{designation_id}", response_model=schemas.Designation)
def update_designation(
    designation_id: int,
    payload: schemas.DesignationUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    d = (
        db.query(models.Designation)
        .filter(models.Designation.id == designation_id, models.Designation.is_deleted == False)  # noqa: E712
        .first()
    )
    if not d:
        raise HTTPException(status_code=404, detail="Designation not found")

    update_data = payload.dict(exclude_unset=True)
    if "name" in update_data:
        existing = db.query(models.Designation).filter(models.Designation.name == update_data["name"]).first()
        if existing and existing.id != designation_id:
            raise HTTPException(status_code=400, detail="Designation name already exists")

    for k, v in update_data.items():
        setattr(d, k, v)

    db.commit()
    db.refresh(d)
    return d


@router.delete("/{designation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_designation(
    designation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    d = (
        db.query(models.Designation)
        .filter(models.Designation.id == designation_id, models.Designation.is_deleted == False)  # noqa: E712
        .first()
    )
    if not d:
        raise HTTPException(status_code=404, detail="Designation not found")

    # Prevent deleting if employees are assigned.
    if db.query(models.Employee).filter(models.Employee.designation_id == designation_id).first():
        raise HTTPException(
            status_code=400,
            detail="Cannot delete designation because employees are assigned. Deactivate it instead.",
        )

    d.is_deleted = True
    d.deleted_at = datetime.utcnow()
    d.deleted_by_user_id = current_user.id
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Cannot delete designation because it is referenced")
    return None
