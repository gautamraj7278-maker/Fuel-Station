from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import List

from app import models, schemas
from app.database import get_db
from app.routers.auth import require_admin

router = APIRouter()


def _normalize_name(name: str) -> str:
    cleaned = str(name or "").strip().lower()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Category name is required")
    return cleaned


def _rename_category(db: Session, *, old_name: str, new_name: str) -> None:
    if old_name == new_name:
        return
    db.query(models.Product).filter(models.Product.fuel_type == old_name).update(
        {models.Product.fuel_type: new_name}, synchronize_session=False
    )
    db.query(models.Nozzle).filter(models.Nozzle.fuel_type == old_name).update(
        {models.Nozzle.fuel_type: new_name}, synchronize_session=False
    )
    db.query(models.Dispenser).filter(models.Dispenser.fuel_type == old_name).update(
        {models.Dispenser.fuel_type: new_name}, synchronize_session=False
    )
    db.query(models.FuelInventory).filter(models.FuelInventory.fuel_type == old_name).update(
        {models.FuelInventory.fuel_type: new_name}, synchronize_session=False
    )
    db.query(models.Sale).filter(models.Sale.fuel_type == old_name).update(
        {models.Sale.fuel_type: new_name}, synchronize_session=False
    )
    db.query(models.InventoryLog).filter(models.InventoryLog.fuel_type == old_name).update(
        {models.InventoryLog.fuel_type: new_name}, synchronize_session=False
    )
    db.query(models.DeletedSale).filter(models.DeletedSale.fuel_type == old_name).update(
        {models.DeletedSale.fuel_type: new_name}, synchronize_session=False
    )


@router.get("/", response_model=List[schemas.ProductCategory])
def list_categories(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    return db.query(models.ProductCategory).order_by(models.ProductCategory.name.asc()).all()


@router.post("/", response_model=schemas.ProductCategory, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: schemas.ProductCategoryCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    name = _normalize_name(payload.name)
    existing = (
        db.query(models.ProductCategory)
        .filter(func.lower(models.ProductCategory.name) == name)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Product category already exists")

    category = models.ProductCategory(name=name, is_active=bool(payload.is_active))
    db.add(category)
    db.flush()

    # Ensure an inventory row exists for this category (stock can stay 0 until used).
    existing_inv = db.query(models.FuelInventory).filter(models.FuelInventory.fuel_type == name).first()
    if existing_inv is None:
        db.add(
            models.FuelInventory(
                fuel_type=name,
                current_stock=0.0,
                price_per_liter=0.0,
                reorder_level=0.0,
            )
        )

    db.commit()
    db.refresh(category)
    return category


@router.put("/{category_id}", response_model=schemas.ProductCategory)
def update_category(
    category_id: int,
    payload: schemas.ProductCategoryUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    category = db.query(models.ProductCategory).filter(models.ProductCategory.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Product category not found")

    update_data = payload.model_dump(exclude_unset=True)
    if "name" in update_data:
        new_name = _normalize_name(update_data["name"])
        existing = (
            db.query(models.ProductCategory)
            .filter(func.lower(models.ProductCategory.name) == new_name, models.ProductCategory.id != category_id)
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="Product category already exists")
        if new_name != category.name and db.query(models.FuelInventory).filter(models.FuelInventory.fuel_type == new_name).first():
            raise HTTPException(status_code=400, detail="Cannot rename category to an existing inventory category")
        old_name = category.name
        category.name = new_name
        _rename_category(db, old_name=old_name, new_name=new_name)

    if "is_active" in update_data:
        category.is_active = bool(update_data["is_active"])

    db.commit()
    db.refresh(category)
    return category


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    category = db.query(models.ProductCategory).filter(models.ProductCategory.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Product category not found")

    if db.query(models.Product).filter(models.Product.fuel_type == category.name, models.Product.is_deleted == False).first():  # noqa: E712
        raise HTTPException(status_code=400, detail="Cannot delete category because products reference it")

    inv_row = db.query(models.FuelInventory).filter(models.FuelInventory.fuel_type == category.name).first()
    if inv_row and float(inv_row.current_stock or 0.0) != 0.0:
        raise HTTPException(status_code=400, detail="Cannot delete category while inventory stock is not zero")

    if inv_row:
        db.delete(inv_row)

    db.delete(category)
    db.commit()
    return None
