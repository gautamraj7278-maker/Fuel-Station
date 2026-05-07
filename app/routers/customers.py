from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app import models, schemas
from app.routers.auth import require_admin

router = APIRouter()

@router.post("/", response_model=schemas.Customer, status_code=status.HTTP_201_CREATED)
def create_customer(
    customer: schemas.CustomerCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    """Create a new customer"""
    # Check if phone already exists
    existing = db.query(models.Customer).filter(
        models.Customer.phone == customer.phone
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Phone number already registered")
    
    # Check if email already exists (if provided)
    if customer.email:
        existing = db.query(models.Customer).filter(
            models.Customer.email == customer.email
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")
    
    db_customer = models.Customer(**customer.dict())
    db.add(db_customer)
    db.commit()
    db.refresh(db_customer)
    return db_customer

@router.get("/", response_model=List[schemas.Customer])
def get_customers(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    """Get all customers with pagination"""
    customers = (
        db.query(models.Customer)
        .filter(models.Customer.is_deleted == False)  # noqa: E712
        .offset(skip)
        .limit(limit)
        .all()
    )
    return customers


@router.get("/deleted", response_model=List[schemas.DeletedItem])
def list_deleted_customers(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    rows = (
        db.query(models.Customer)
        .filter(models.Customer.is_deleted == True)  # noqa: E712
        .order_by(models.Customer.deleted_at.desc(), models.Customer.id.desc())
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


@router.post("/deleted/{customer_id}/restore", response_model=schemas.Customer)
def restore_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    customer = (
        db.query(models.Customer)
        .filter(models.Customer.id == customer_id, models.Customer.is_deleted == True)  # noqa: E712
        .first()
    )
    if not customer:
        raise HTTPException(status_code=404, detail="Deleted customer not found")

    customer.is_deleted = False
    customer.deleted_at = None
    customer.deleted_by_user_id = None
    db.commit()
    db.refresh(customer)
    return customer


@router.delete("/deleted/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def purge_deleted_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    customer = (
        db.query(models.Customer)
        .filter(models.Customer.id == customer_id, models.Customer.is_deleted == True)  # noqa: E712
        .first()
    )
    if not customer:
        raise HTTPException(status_code=404, detail="Deleted customer not found")

    try:
        db.delete(customer)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Cannot purge customer because it is referenced by other records")
    return None

@router.get("/{customer_id}", response_model=schemas.Customer)
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    """Get a specific customer by ID"""
    customer = (
        db.query(models.Customer)
        .filter(models.Customer.id == customer_id, models.Customer.is_deleted == False)  # noqa: E712
        .first()
    )
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer

@router.put("/{customer_id}", response_model=schemas.Customer)
def update_customer(
    customer_id: int,
    customer_update: schemas.CustomerUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    """Update a customer"""
    customer = (
        db.query(models.Customer)
        .filter(models.Customer.id == customer_id, models.Customer.is_deleted == False)  # noqa: E712
        .first()
    )
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    update_data = customer_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(customer, field, value)
    
    db.commit()
    db.refresh(customer)
    return customer

@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    """Delete a customer"""
    customer = (
        db.query(models.Customer)
        .filter(models.Customer.id == customer_id, models.Customer.is_deleted == False)  # noqa: E712
        .first()
    )
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    customer.is_deleted = True
    customer.deleted_at = datetime.utcnow()
    customer.deleted_by_user_id = current_user.id
    db.commit()
    return None
