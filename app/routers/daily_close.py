from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import date

from app.database import get_db
from app import models, schemas
from app.routers.auth import require_ops_access

router = APIRouter()


@router.post("/", response_model=schemas.DailyClose, status_code=status.HTTP_201_CREATED)
def create_daily_close(
    payload: schemas.DailyCloseCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access),
):
    # one close per date
    existing = db.query(models.DailyClose).filter(models.DailyClose.business_date == payload.business_date).first()
    if existing:
        raise HTTPException(status_code=400, detail="Daily close already exists for this date")

    record = models.DailyClose(
        business_date=payload.business_date,
        opening_cash=payload.opening_cash,
        closing_cash=payload.closing_cash,
        notes=payload.notes,
        user_id=current_user.id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/", response_model=List[schemas.DailyClose])
def list_daily_closes(
    business_date: Optional[date] = None,
    business_date_from: Optional[date] = None,
    business_date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access),
):
    query = db.query(models.DailyClose)
    if business_date is not None:
        query = query.filter(models.DailyClose.business_date == business_date)
    else:
        if business_date_from is not None:
            query = query.filter(models.DailyClose.business_date >= business_date_from)
        if business_date_to is not None:
            query = query.filter(models.DailyClose.business_date <= business_date_to)
    return query.order_by(models.DailyClose.business_date.desc()).all()


@router.get("/summary/{business_date}")
def daily_close_summary(
    business_date: date,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access),
):
    date_filter = (models.Sale.business_date == business_date) | (func.date(models.Sale.created_at) == business_date)
    sales_only = models.Sale.transaction_type == models.TransactionType.SALE

    sales = db.query(
        func.count(models.Sale.id).label("transactions"),
        func.sum(models.Sale.quantity).label("liters"),
        func.sum(models.Sale.total_amount).label("revenue"),
    ).filter(date_filter, sales_only).first()

    legacy_deposit = (
        db.query(func.sum(models.Sale.total_deposit))
        .filter(date_filter, sales_only, models.Sale.sales_batch_id.is_(None))
        .scalar()
    )
    batch_deposit = (
        db.query(func.sum(models.SalesBatch.total_deposit))
        .filter(models.SalesBatch.business_date == business_date)
        .scalar()
    )
    total_deposit = float((legacy_deposit or 0.0) + (batch_deposit or 0.0))

    close = db.query(models.DailyClose).filter(models.DailyClose.business_date == business_date).first()

    return {
        "business_date": business_date.isoformat(),
        "sales": {
            "transactions": sales.transactions or 0,
            "liters": float(sales.liters or 0),
            "revenue": float(sales.revenue or 0),
            "deposit": total_deposit,
        },
        "daily_close": None
        if close is None
        else {
            "opening_cash": float(close.opening_cash),
            "closing_cash": float(close.closing_cash),
            "notes": close.notes,
            "created_at": close.created_at.isoformat(),
        },
    }
