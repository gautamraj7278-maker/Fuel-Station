from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.routers.auth import require_admin

router = APIRouter()


@router.get("/", response_model=List[schemas.ProductPrice])
def list_product_prices(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
    product_id: Optional[int] = None,
    limit: int = Query(200, ge=1, le=1000),
):
    q = db.query(models.ProductPrice)
    if product_id is not None:
        q = q.filter(models.ProductPrice.product_id == product_id)

    return q.order_by(models.ProductPrice.effective_date.desc(), models.ProductPrice.created_at.desc()).limit(limit).all()


@router.get("/latest", response_model=List[schemas.ProductPrice])
def list_latest_prices(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    # SQLite-friendly: fetch latest per product by ordering and picking first in Python.
    rows = (
        db.query(models.ProductPrice)
        .order_by(models.ProductPrice.product_id.asc(), models.ProductPrice.effective_date.desc(), models.ProductPrice.created_at.desc())
        .all()
    )
    latest = {}
    for r in rows:
        if r.product_id not in latest:
            latest[r.product_id] = r
    return list(latest.values())


@router.post("/", response_model=schemas.ProductPrice, status_code=status.HTTP_201_CREATED)
def create_product_price(
    payload: schemas.ProductPriceCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    product = db.query(models.Product).filter(models.Product.id == payload.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    effective_date = payload.effective_date or datetime.utcnow().date()

    pp = models.ProductPrice(
        product_id=payload.product_id,
        price_per_liter=float(payload.price_per_liter),
        effective_date=effective_date,
        remarks=payload.remarks,
        created_by_user_id=current_user.id,
    )
    db.add(pp)

    # Keep legacy FuelInventory price in sync for the product fuel_type.
    inv = db.query(models.FuelInventory).filter(models.FuelInventory.fuel_type == product.fuel_type).first()
    if inv:
        inv.price_per_liter = float(payload.price_per_liter)
    else:
        db.add(
            models.FuelInventory(
                fuel_type=product.fuel_type,
                current_stock=0.0,
                price_per_liter=float(payload.price_per_liter),
                reorder_level=0.0,
            )
        )

    db.commit()
    db.refresh(pp)
    return pp
