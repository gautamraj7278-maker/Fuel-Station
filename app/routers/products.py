from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app import models, schemas
from app.routers.auth import require_admin

router = APIRouter()


def _normalize_category(name: str) -> str:
    cleaned = str(name or "").strip().lower()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Product category is required")
    return cleaned


def _require_category(db: Session, name: str) -> str:
    cleaned = _normalize_category(name)
    category = (
        db.query(models.ProductCategory)
        .filter(func.lower(models.ProductCategory.name) == cleaned)
        .first()
    )
    if not category:
        raise HTTPException(status_code=400, detail="Invalid product category")
    if not category.is_active:
        raise HTTPException(status_code=400, detail="Selected product category is inactive")
    return cleaned


@router.post("/", response_model=schemas.Product, status_code=status.HTTP_201_CREATED)
def create_product(
    product: schemas.ProductCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    existing = db.query(models.Product).filter(models.Product.product_name == product.product_name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Product name already exists")

    category_name = _require_category(db, product.fuel_type)
    db_product = models.Product(
        product_name=product.product_name,
        fuel_type=category_name,
        is_active=product.is_active,
    )
    db.add(db_product)

    # Ensure a matching inventory row exists for this category.
    if not db.query(models.FuelInventory).filter(models.FuelInventory.fuel_type == category_name).first():
        db.add(
            models.FuelInventory(
                fuel_type=category_name,
                current_stock=0.0,
                price_per_liter=0.0,
                reorder_level=0.0,
            )
        )
    db.commit()
    db.refresh(db_product)
    return db_product


@router.get("/", response_model=List[schemas.Product])
def list_products(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    return (
        db.query(models.Product)
        .filter(models.Product.is_deleted == False)  # noqa: E712
        .order_by(models.Product.product_name.asc())
        .all()
    )


@router.get("/deleted", response_model=List[schemas.DeletedItem])
def list_deleted_products(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    rows = (
        db.query(models.Product)
        .filter(models.Product.is_deleted == True)  # noqa: E712
        .order_by(models.Product.deleted_at.desc(), models.Product.id.desc())
        .all()
    )
    return [
        schemas.DeletedItem(
            id=r.id,
            label=r.product_name,
            deleted_at=r.deleted_at,
            deleted_by_user_id=r.deleted_by_user_id,
            deleted_by_username=(r.deleted_by.username if r.deleted_by else None),
        )
        for r in rows
    ]


@router.post("/deleted/{product_id}/restore", response_model=schemas.Product)
def restore_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    product = (
        db.query(models.Product)
        .filter(models.Product.id == product_id, models.Product.is_deleted == True)  # noqa: E712
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="Deleted product not found")

    product.is_deleted = False
    product.deleted_at = None
    product.deleted_by_user_id = None
    db.commit()
    db.refresh(product)
    return product


@router.delete("/deleted/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def purge_deleted_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    product = (
        db.query(models.Product)
        .filter(models.Product.id == product_id, models.Product.is_deleted == True)  # noqa: E712
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="Deleted product not found")

    try:
        db.delete(product)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Cannot purge product because it is referenced by other records")
    return None


@router.put("/{product_id}", response_model=schemas.Product)
def update_product(
    product_id: int,
    payload: schemas.ProductUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    product = (
        db.query(models.Product)
        .filter(models.Product.id == product_id, models.Product.is_deleted == False)  # noqa: E712
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.is_deleted:
        return None

    update_data = payload.dict(exclude_unset=True)
    if "product_name" in update_data:
        existing = db.query(models.Product).filter(models.Product.product_name == update_data["product_name"]).first()
        if existing and existing.id != product_id:
            raise HTTPException(status_code=400, detail="Product name already exists")

    if "fuel_type" in update_data:
        update_data["fuel_type"] = _require_category(db, update_data["fuel_type"])

    for field, value in update_data.items():
        setattr(product, field, value)

    db.commit()
    db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if db.query(models.Tank).filter(models.Tank.product_id == product_id).first():
        raise HTTPException(status_code=400, detail="Cannot delete product because tanks reference it")
    if db.query(models.Nozzle).filter(models.Nozzle.product_id == product_id).first():
        raise HTTPException(status_code=400, detail="Cannot delete product because nozzles reference it")
    if db.query(models.Sale).filter(models.Sale.product_id == product_id).first():
        raise HTTPException(status_code=400, detail="Cannot delete product because sales reference it")
    if db.query(models.TankTransfer).filter(models.TankTransfer.product_id == product_id).first():
        raise HTTPException(status_code=400, detail="Cannot delete product because transfers reference it")

    product.is_deleted = True
    product.deleted_at = datetime.utcnow()
    product.deleted_by_user_id = current_user.id
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Cannot delete product because it is referenced by other records")
    return None
