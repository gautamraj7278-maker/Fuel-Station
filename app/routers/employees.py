from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app import models, schemas
from app.routers.auth import require_admin

router = APIRouter()


@router.get("/", response_model=List[schemas.Employee])
def list_employees(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    return (
        db.query(models.Employee)
        .filter(models.Employee.is_deleted == False)  # noqa: E712
        .order_by(models.Employee.employee_name.asc())
        .all()
    )


@router.get("/deleted", response_model=List[schemas.DeletedItem])
def list_deleted_employees(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    rows = (
        db.query(models.Employee)
        .filter(models.Employee.is_deleted == True)  # noqa: E712
        .order_by(models.Employee.deleted_at.desc(), models.Employee.id.desc())
        .all()
    )
    return [
        schemas.DeletedItem(
            id=r.id,
            label=r.employee_name,
            deleted_at=r.deleted_at,
            deleted_by_user_id=r.deleted_by_user_id,
            deleted_by_username=(r.deleted_by.username if r.deleted_by else None),
        )
        for r in rows
    ]


@router.post("/deleted/{employee_id}/restore", response_model=schemas.Employee)
def restore_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    e = (
        db.query(models.Employee)
        .filter(models.Employee.id == employee_id, models.Employee.is_deleted == True)  # noqa: E712
        .first()
    )
    if not e:
        raise HTTPException(status_code=404, detail="Deleted employee not found")

    e.is_deleted = False
    e.deleted_at = None
    e.deleted_by_user_id = None
    db.commit()
    db.refresh(e)
    return e


@router.delete("/deleted/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
def purge_deleted_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    employee = (
        db.query(models.Employee)
        .filter(models.Employee.id == employee_id, models.Employee.is_deleted == True)  # noqa: E712
        .first()
    )
    if not employee:
        raise HTTPException(status_code=404, detail="Deleted employee not found")

    try:
        db.delete(employee)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Cannot purge employee because it is referenced by other records")
    return None


@router.post("/", response_model=schemas.Employee, status_code=status.HTTP_201_CREATED)
def create_employee(
    payload: schemas.EmployeeCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    if payload.id_no:
        existing = db.query(models.Employee).filter(models.Employee.id_no == payload.id_no).first()
        if existing:
            raise HTTPException(status_code=400, detail="ID No already exists")

    if payload.designation_id is not None:
        d = db.query(models.Designation).filter(models.Designation.id == payload.designation_id).first()
        if not d:
            raise HTTPException(status_code=400, detail="Invalid designation_id")

    e = models.Employee(**payload.dict())
    db.add(e)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Failed to create employee (duplicate/invalid data)")

    db.refresh(e)
    return e


@router.put("/{employee_id}", response_model=schemas.Employee)
def update_employee(
    employee_id: int,
    payload: schemas.EmployeeUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    e = (
        db.query(models.Employee)
        .filter(models.Employee.id == employee_id, models.Employee.is_deleted == False)  # noqa: E712
        .first()
    )
    if not e:
        raise HTTPException(status_code=404, detail="Employee not found")

    update_data = payload.dict(exclude_unset=True)

    if "id_no" in update_data and update_data["id_no"]:
        existing = db.query(models.Employee).filter(models.Employee.id_no == update_data["id_no"]).first()
        if existing and existing.id != employee_id:
            raise HTTPException(status_code=400, detail="ID No already exists")

    if "designation_id" in update_data and update_data["designation_id"] is not None:
        d = db.query(models.Designation).filter(models.Designation.id == update_data["designation_id"]).first()
        if not d:
            raise HTTPException(status_code=400, detail="Invalid designation_id")

    for k, v in update_data.items():
        setattr(e, k, v)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Failed to update employee (duplicate/invalid data)")

    db.refresh(e)
    return e


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    e = (
        db.query(models.Employee)
        .filter(models.Employee.id == employee_id, models.Employee.is_deleted == False)  # noqa: E712
        .first()
    )
    if not e:
        raise HTTPException(status_code=404, detail="Employee not found")

    e.is_deleted = True
    e.deleted_at = datetime.utcnow()
    e.deleted_by_user_id = current_user.id
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Cannot delete employee because it is referenced")
    return None
