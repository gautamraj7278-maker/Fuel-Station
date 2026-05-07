from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date
from sqlalchemy import func, or_, case
from app.database import get_db
from app import models, schemas
from app.routers.auth import require_ops_access

router = APIRouter()


def _normalize_category(name: str) -> str:
    return str(name or "").strip().lower()


def _ensure_category_exists(db: Session, name: str) -> str:
    cleaned = _normalize_category(name)
    if not cleaned:
        raise HTTPException(status_code=400, detail="Product category is required")
    category = (
        db.query(models.ProductCategory)
        .filter(func.lower(models.ProductCategory.name) == cleaned)
        .first()
    )
    if not category:
        raise HTTPException(status_code=404, detail="Product category not found")
    return cleaned


def _ensure_inventory_rows_for_configured_products(db: Session) -> None:
    """Ensure FuelInventory rows exist for fuel types that have products.

    Without this, a fresh database would return an empty inventory screen until someone
    manually initializes inventory rows.
    """
    fuel_types = [
        ft
        for (ft,) in (
            db.query(models.Product.fuel_type)
            .distinct()
            .all()
        )
        if ft is not None
    ]

    for fuel_type in fuel_types:
        existing = db.query(models.FuelInventory).filter(models.FuelInventory.fuel_type == fuel_type).first()
        if existing is not None:
            continue

        db.add(
            models.FuelInventory(
                fuel_type=fuel_type,
                current_stock=0.0,
                price_per_liter=0.0,
                reorder_level=0.0,
            )
        )

    db.flush()


def _dip_volume_litres(reading: Optional[models.TankDipReading]) -> Optional[float]:
    if reading is None:
        return None
    if reading.manual_volume_litres is not None:
        return float(reading.manual_volume_litres)
    if reading.computed_volume_litres is not None:
        return float(reading.computed_volume_litres)
    return None


def _get_or_auto_opening(db: Session, *, tank_id: int, business_date: date) -> Optional[models.TankDipReading]:
    opening = (
        db.query(models.TankDipReading)
        .filter(
            models.TankDipReading.tank_id == tank_id,
            models.TankDipReading.business_date == business_date,
            models.TankDipReading.dip_type == models.TankDipType.OPENING,
        )
        .first()
    )
    if opening:
        return opening

    prev_date = business_date.fromordinal(business_date.toordinal() - 1)
    prev_closing = (
        db.query(models.TankDipReading)
        .filter(
            models.TankDipReading.tank_id == tank_id,
            models.TankDipReading.business_date == prev_date,
            models.TankDipReading.dip_type == models.TankDipType.CLOSING,
        )
        .first()
    )
    if not prev_closing:
        return None

    auto = models.TankDipReading(
        tank_id=tank_id,
        business_date=business_date,
        dip_type=models.TankDipType.OPENING,
        dips_mm=float(prev_closing.dips_mm),
        computed_volume_litres=prev_closing.computed_volume_litres,
        manual_volume_litres=prev_closing.manual_volume_litres,
        is_auto=True,
        created_by_user_id=None,
    )
    db.add(auto)
    db.flush()
    return auto

@router.post("/", response_model=schemas.FuelInventory, status_code=status.HTTP_201_CREATED)
def create_inventory(
    inventory: schemas.FuelInventoryCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access)
):
    """Create or initialize fuel inventory"""
    # Check if inventory already exists
    fuel_type = _ensure_category_exists(db, inventory.fuel_type)
    existing = db.query(models.FuelInventory).filter(
        models.FuelInventory.fuel_type == fuel_type
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Inventory for this category already exists")
    
    db_inventory = models.FuelInventory(
        fuel_type=fuel_type,
        current_stock=inventory.current_stock,
        price_per_liter=inventory.price_per_liter,
        reorder_level=inventory.reorder_level,
    )
    db.add(db_inventory)
    
    # Log the initialization
    log = models.InventoryLog(
        fuel_type=fuel_type,
        action="initialize",
        quantity=inventory.current_stock,
        previous_stock=0,
        new_stock=inventory.current_stock,
        notes="Initial inventory setup"
    )
    db.add(log)
    
    db.commit()
    db.refresh(db_inventory)
    return db_inventory

@router.get("/", response_model=List[schemas.FuelInventory])
def get_inventory(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access)
):
    """Get all fuel inventory"""
    inventory = db.query(models.FuelInventory).all()
    return inventory


@router.get("/daily-status", response_model=List[schemas.FuelInventoryDailyStatus])
def get_inventory_daily_status(
    business_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access),
):
    """Daily inventory status driven by tank opening dips and day transactions.

    - Opening stock: sum of OPENING dips for MAIN tanks (auto-created from previous CLOSING when available).
    - Receipts: sum of confirmed tanker receipt received litres into MAIN tanks.
    - Sales: sum of SALE quantities for the day.
    - Testings: sum of testing quantities moved to buffer for the day.
    - Buffer returns: sum of BUFFER_TO_MAIN transfers for the day.
    - Book stock (main) = opening + receipts - sales - testings + buffer_returns.
    - Physical closing: sum of CLOSING dips for MAIN tanks (if entered).
    """
    _ = current_user

    if business_date is None:
        business_date = date.today()

    # Make sure a fresh database shows inventory rows as soon as products exist.
    _ensure_inventory_rows_for_configured_products(db)

    inventory_rows = db.query(models.FuelInventory).order_by(models.FuelInventory.fuel_type.asc()).all()

    results: List[schemas.FuelInventoryDailyStatus] = []
    any_auto_openings = False

    for inv in inventory_rows:
        fuel_type = inv.fuel_type

        product_ids = [
            int(pid)
            for (pid,) in (
                db.query(models.Product.id)
                .filter(models.Product.fuel_type == fuel_type)
                .all()
            )
        ]

        main_tank_ids = [
            int(tid)
            for (tid,) in (
                db.query(models.Tank.id)
                .filter(models.Tank.product_id.in_(product_ids), models.Tank.is_buffer == False)  # noqa: E712
                .all()
            )
        ] if product_ids else []

        opening_stock = 0.0
        for tank_id in main_tank_ids:
            opening = _get_or_auto_opening(db, tank_id=tank_id, business_date=business_date)
            if opening is not None and opening.is_auto:
                any_auto_openings = True
            vol = _dip_volume_litres(opening)
            opening_stock += float(vol or 0.0)

        closing_rows = (
            db.query(models.TankDipReading)
            .filter(
                models.TankDipReading.tank_id.in_(main_tank_ids),
                models.TankDipReading.business_date == business_date,
                models.TankDipReading.dip_type == models.TankDipType.CLOSING,
            )
            .all()
        ) if main_tank_ids else []
        physical_closing_stock = sum(float(_dip_volume_litres(r) or 0.0) for r in closing_rows) if closing_rows else None

        receipts = 0.0
        if product_ids:
            receipts = float(
                (
                    db.query(func.sum(models.TankerReceiptLine.received_volume_litres))
                    .join(models.TankerReceipt, models.TankerReceipt.id == models.TankerReceiptLine.receipt_id)
                    .join(models.Tank, models.Tank.id == models.TankerReceiptLine.tank_id)
                    .filter(
                        models.TankerReceipt.status == models.TankerReceiptStatus.CONFIRMED,
                        models.TankerReceipt.receipt_date == business_date,
                        models.Tank.is_buffer == False,  # noqa: E712
                        models.TankerReceiptLine.product_id.in_(product_ids),
                    )
                    .scalar()
                )
                or 0.0
            )

        sale_date = func.coalesce(models.Sale.business_date, func.date(models.Sale.created_at))
        sale_product_filter = (
            models.Sale.product_id.in_(product_ids)
            if product_ids
            else (models.Sale.product_id.is_(None) & (models.Sale.fuel_type == fuel_type))
        )
        base_sale_filter = [
            sale_date == business_date,
            or_(
                sale_product_filter,
                (models.Sale.product_id.is_(None) & (models.Sale.fuel_type == fuel_type)),
            ),
        ]

        sales_qty = float(
            (
                db.query(func.sum(models.Sale.quantity))
                .filter(*base_sale_filter, models.Sale.transaction_type == models.TransactionType.SALE)
                .scalar()
            )
            or 0.0
        )
        testing_qty = float(
            (
                db.query(
                    func.sum(
                        case(
                            (models.Sale.transaction_type == models.TransactionType.TESTING, models.Sale.quantity),
                            else_=func.coalesce(models.Sale.testing_quantity, 0.0),
                        )
                    )
                )
                .filter(*base_sale_filter)
                .scalar()
            )
            or 0.0
        )

        buffer_returns_qty = 0.0
        if product_ids:
            transfer_date = func.date(models.TankTransfer.created_at)
            buffer_returns_qty = float(
                (
                    db.query(func.sum(models.TankTransfer.volume))
                    .filter(
                        transfer_date == business_date.isoformat(),
                        models.TankTransfer.transfer_type == models.TankTransferType.BUFFER_TO_MAIN,
                        models.TankTransfer.product_id.in_(product_ids),
                    )
                    .scalar()
                )
                or 0.0
            )

        book_stock = float(opening_stock + receipts - sales_qty - testing_qty + buffer_returns_qty)
        physical = float(physical_closing_stock) if physical_closing_stock is not None else None
        variance = float((physical - book_stock)) if physical is not None else None

        results.append(
            schemas.FuelInventoryDailyStatus(
                fuel_type=fuel_type,
                opening_stock=float(opening_stock),
                receipts=float(receipts),
                sales=float(sales_qty),
                testings=float(testing_qty),
                buffer_returns=float(buffer_returns_qty),
                book_stock=float(book_stock),
                physical_closing_stock=physical,
                variance=variance,
                price_per_liter=float(inv.price_per_liter or 0.0),
                reorder_level=float(inv.reorder_level or 0.0),
                needs_reorder=float(book_stock) <= float(inv.reorder_level or 0.0),
                last_updated=inv.last_updated,
            )
        )

    if any_auto_openings:
        db.commit()  # persist any auto-openings created during status computation

    return results

@router.get("/{fuel_type}", response_model=schemas.FuelInventory)
def get_inventory_by_type(
    fuel_type: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access)
):
    """Get inventory for a specific fuel type"""
    normalized = _normalize_category(fuel_type)
    inventory = db.query(models.FuelInventory).filter(
        models.FuelInventory.fuel_type == normalized
    ).first()
    
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventory not found")
    return inventory

@router.put("/{fuel_type}", response_model=schemas.FuelInventory)
def update_inventory(
    fuel_type: str,
    inventory_update: schemas.FuelInventoryUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access)
):
    """Update fuel inventory"""
    normalized = _normalize_category(fuel_type)
    inventory = db.query(models.FuelInventory).filter(
        models.FuelInventory.fuel_type == normalized
    ).first()
    
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventory not found")
    
    update_data = inventory_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(inventory, field, value)
    
    db.commit()
    db.refresh(inventory)
    return inventory

@router.post("/restock/{fuel_type}")
def restock_fuel_deprecated(
    fuel_type: str,
    quantity: float,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access),
):
    """Deprecated: inventory restocking must happen via tanker receipts confirmation."""
    _ = db
    _ = current_user
    _ = quantity
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=f"Manual restock is disabled. Create and confirm a tanker receipt to restock {fuel_type}.",
    )

@router.get("/logs/all", response_model=List[schemas.InventoryLog])
def get_inventory_logs(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access)
):
    """Get inventory change logs"""
    logs = db.query(models.InventoryLog).order_by(
        models.InventoryLog.created_at.desc()
    ).offset(skip).limit(limit).all()
    return logs
