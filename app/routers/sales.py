from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from datetime import datetime, date
import uuid
from app.database import get_db
from app import models, schemas
from app.deletion_requests import queue_deletion_request
from app.routers.auth import get_current_user, require_admin, require_manager_or_admin, require_ops_access
from app.routers.shift_config import resolve_shift_for_datetime

router = APIRouter()


def _coerce_testing_quantity(value: Optional[float]) -> float:
    if value is None:
        return 0.0
    try:
        qty = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="testing_quantity must be a number")
    if qty < 0:
        raise HTTPException(status_code=400, detail="testing_quantity must be >= 0")
    return qty


def _testing_qty_from_sale(sale: models.Sale) -> float:
    if sale.testing_quantity is not None:
        return float(sale.testing_quantity or 0.0)
    if sale.transaction_type == models.TransactionType.TESTING:
        return float(sale.quantity or 0.0)
    return 0.0


def _sales_qty_from_sale(sale: models.Sale) -> float:
    if sale.transaction_type == models.TransactionType.TESTING:
        return 0.0
    return float(sale.quantity or 0.0)


def _ensure_operator_employee(db: Session, operator_employee_id: Optional[int]) -> None:
    if operator_employee_id is None:
        return
    employee = db.query(models.Employee).filter(models.Employee.id == operator_employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Operator employee not found")
    if not employee.is_active:
        raise HTTPException(status_code=400, detail="Selected operator employee is inactive")


def _create_sale_line_from_batch(
    line: schemas.SalesBatchLineCreate,
    *,
    batch: models.SalesBatch,
    db: Session,
    current_user: models.User,
    seen_meters: set[int],
    seen_nozzles: set[int],
) -> models.Sale:
    dispenser_id = batch.dispenser_id
    business_date = batch.business_date
    shift = batch.shift

    tx_type = models.TransactionType.SALE

    total_dispensed = None
    sales_qty = None
    testing_qty = None
    computed_fuel_type = None
    computed_nozzle_id = line.nozzle_id
    computed_product_id = None
    computed_tank_id = None
    opening_reading = None
    closing_reading = None
    meter = None

    if line.meter_id is not None:
        meter = db.query(models.Meter).filter(models.Meter.id == line.meter_id).first()
        if not meter:
            raise HTTPException(status_code=404, detail="Meter not found")
        if not meter.is_active:
            raise HTTPException(status_code=400, detail="Meter is not active")
        if meter.id in seen_meters:
            raise HTTPException(status_code=400, detail="Duplicate meter entry in this batch")

        nozzle = db.query(models.Nozzle).filter(models.Nozzle.id == meter.nozzle_id).first()
        if not nozzle:
            raise HTTPException(status_code=400, detail="Meter is not linked to a valid nozzle")
        if nozzle.dispenser_id != dispenser_id:
            raise HTTPException(status_code=400, detail="Meter/nozzle does not belong to selected dispenser")
        if not nozzle.is_active:
            raise HTTPException(status_code=400, detail="Nozzle is not active")
        if nozzle.id in seen_nozzles:
            raise HTTPException(status_code=400, detail="Duplicate nozzle entry in this batch")

        if line.nozzle_id is not None and line.nozzle_id != nozzle.id:
            raise HTTPException(status_code=400, detail="Selected nozzle does not match meter")

        computed_nozzle_id = nozzle.id
        computed_fuel_type = nozzle.fuel_type
        computed_product_id = nozzle.product_id
        computed_tank_id = nozzle.tank_id

        if computed_product_id is None or computed_tank_id is None:
            raise HTTPException(status_code=400, detail="Nozzle must be configured with product_id and tank_id")

        product = db.query(models.Product).filter(models.Product.id == computed_product_id).first()
        if not product:
            raise HTTPException(status_code=400, detail="Nozzle product configuration is invalid")

        tank = db.query(models.Tank).filter(models.Tank.id == computed_tank_id).first()
        if not tank:
            raise HTTPException(status_code=400, detail="Nozzle tank configuration is invalid")
        if tank.product_id != product.id:
            raise HTTPException(status_code=400, detail="Nozzle tank product mismatch")

        if line.closing_meter_reading is None:
            raise HTTPException(status_code=400, detail="closing_meter_reading is required when meter_id is provided")

        opening_reading = float(meter.last_reading or 0.0)
        closing_reading = float(line.closing_meter_reading)

        if closing_reading < 0:
            raise HTTPException(status_code=400, detail="closing_meter_reading must be >= 0")

        if meter.max_value is not None:
            max_value = float(meter.max_value)
            if opening_reading > max_value or closing_reading > max_value:
                raise HTTPException(status_code=400, detail="Meter readings must be <= configured max_value")

            if closing_reading >= opening_reading:
                total_dispensed = closing_reading - opening_reading
            else:
                total_dispensed = (max_value - opening_reading) + closing_reading
        else:
            if closing_reading < opening_reading:
                raise HTTPException(status_code=400, detail="closing_meter_reading cannot be less than opening when max_value is not configured")
            total_dispensed = closing_reading - opening_reading

        if total_dispensed is None or total_dispensed < 0:
            raise HTTPException(status_code=400, detail="Unable to compute dispensed quantity")

        existing = (
            db.query(models.Sale)
            .filter(
                models.Sale.meter_id == meter.id,
                models.Sale.business_date == business_date,
                models.Sale.shift == shift,
            )
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="A sale entry already exists for this meter, shift, and date")

        seen_meters.add(meter.id)
        seen_nozzles.add(nozzle.id)
    else:
        if line.nozzle_id is None:
            raise HTTPException(status_code=400, detail="nozzle_id is required when meter_id is not provided")

        sales_qty = float(line.quantity or 0.0)
        testing_qty = _coerce_testing_quantity(line.testing_quantity)
        total_dispensed = float(sales_qty + testing_qty)
        if total_dispensed < 0:
            raise HTTPException(status_code=400, detail="quantity/testing_quantity must be >= 0")

        nozzle = db.query(models.Nozzle).filter(models.Nozzle.id == line.nozzle_id).first()
        if not nozzle:
            raise HTTPException(status_code=404, detail="Nozzle not found")
        if nozzle.dispenser_id != dispenser_id:
            raise HTTPException(status_code=400, detail="Nozzle does not belong to selected dispenser")
        if not nozzle.is_active:
            raise HTTPException(status_code=400, detail="Nozzle is not active")
        if nozzle.product_id is None:
            raise HTTPException(status_code=400, detail="Nozzle must be configured with product_id")
        if nozzle.id in seen_nozzles:
            raise HTTPException(status_code=400, detail="Duplicate nozzle entry in this batch")

        computed_fuel_type = nozzle.fuel_type
        computed_product_id = nozzle.product_id
        computed_tank_id = nozzle.tank_id
        seen_nozzles.add(nozzle.id)

    if line.meter_id is not None:
        testing_qty = _coerce_testing_quantity(line.testing_quantity)
        if total_dispensed is None:
            raise HTTPException(status_code=400, detail="Unable to compute dispensed quantity")
        if testing_qty > total_dispensed + 1e-6:
            raise HTTPException(status_code=400, detail="Testing quantity cannot exceed dispensed quantity")
        sales_qty = float(total_dispensed) - float(testing_qty)

    inventory = db.query(models.FuelInventory).filter(models.FuelInventory.fuel_type == computed_fuel_type).first()
    if not inventory:
        raise HTTPException(status_code=404, detail="Fuel type not found in inventory")

    resolved_price_per_liter = float(inventory.price_per_liter)
    if computed_product_id is not None:
        latest_price = (
            db.query(models.ProductPrice)
            .filter(models.ProductPrice.product_id == computed_product_id)
            .order_by(models.ProductPrice.effective_date.desc(), models.ProductPrice.created_at.desc())
            .first()
        )
        if latest_price is not None:
            resolved_price_per_liter = float(latest_price.price_per_liter)

    if sales_qty is not None and inventory.current_stock < sales_qty:
        raise HTTPException(status_code=400, detail="Insufficient fuel stock")

    total_amount = (sales_qty or 0.0) * resolved_price_per_liter

    transaction_id = f"TXN{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"

    db_sale = models.Sale(
        transaction_id=transaction_id,
        dispenser_id=dispenser_id,
        sales_batch_id=batch.id,
        nozzle_id=computed_nozzle_id,
        meter_id=line.meter_id,
        user_id=current_user.id,
        fuel_type=computed_fuel_type,
        product_id=computed_product_id,
        quantity=float(sales_qty or 0.0),
        testing_quantity=float(testing_qty or 0.0),
        opening_meter_reading=opening_reading,
        closing_meter_reading=closing_reading,
        price_per_liter=resolved_price_per_liter,
        total_amount=total_amount,
        business_date=business_date,
        operator_employee_id=batch.operator_employee_id,
        deposit_cash=0.0,
        deposit_online=0.0,
        total_deposit=0.0,
        remarks=None,
        transaction_type=tx_type,
        shift=shift,
        operator_id=current_user.id,
    )
    db.add(db_sale)

    nozzle_tank = None
    if computed_tank_id is not None:
        nozzle_tank = db.query(models.Tank).filter(models.Tank.id == computed_tank_id).first()
        if nozzle_tank is None:
            raise HTTPException(status_code=400, detail="Configured nozzle tank not found")
        if total_dispensed is None:
            raise HTTPException(status_code=400, detail="Unable to compute dispensed quantity")
        if float(nozzle_tank.current_volume or 0.0) < total_dispensed:
            raise HTTPException(status_code=400, detail="Insufficient tank volume")

        nozzle_tank.current_volume = float(nozzle_tank.current_volume or 0.0) - total_dispensed

    if sales_qty is not None and sales_qty > 0:
        previous_stock = float(inventory.current_stock or 0.0)
        inventory.current_stock = previous_stock - float(sales_qty)
        inventory_log = models.InventoryLog(
            fuel_type=computed_fuel_type,
            action="sale",
            quantity=float(sales_qty),
            previous_stock=previous_stock,
            new_stock=inventory.current_stock,
            notes=f"Sale transaction: {transaction_id}",
        )
        db.add(inventory_log)

    if (testing_qty or 0.0) > 0 and computed_product_id is not None and nozzle_tank is not None:
        product = db.query(models.Product).filter(models.Product.id == computed_product_id).first()
        if not product:
            raise HTTPException(status_code=400, detail="Product not found for testing")

        buffer_name = f"BUFFER-{product.product_name}".upper()
        buffer_tank = db.query(models.Tank).filter(models.Tank.tank_name == buffer_name).first()
        if not buffer_tank:
            buffer_tank = models.Tank(
                tank_name=buffer_name,
                product_id=product.id,
                capacity=10**12,
                current_volume=0.0,
                is_buffer=True,
                remarks="Auto-created buffer tank",
            )
            db.add(buffer_tank)
            db.flush()

        buffer_tank.current_volume = float(buffer_tank.current_volume or 0.0) + float(testing_qty)
        transfer = models.TankTransfer(
            from_tank_id=nozzle_tank.id,
            to_tank_id=buffer_tank.id,
            product_id=product.id,
            volume=float(testing_qty),
            transfer_type=models.TankTransferType.TESTING_TO_BUFFER,
            user_id=current_user.id,
        )
        db.add(transfer)

    if meter is not None:
        meter.last_reading = closing_reading

    return db_sale


def compute_sale_preview(
    sale: schemas.SaleCreate,
    *,
    db: Session,
    current_user: models.User,
) -> dict:
    """Compute sale quantities and pricing without persisting."""
    # Check dispenser exists and is active
    dispenser = db.query(models.Dispenser).filter(models.Dispenser.id == sale.dispenser_id).first()
    if not dispenser:
        raise HTTPException(status_code=404, detail="Dispenser not found")
    if not dispenser.is_active:
        raise HTTPException(status_code=400, detail="Dispenser is not active")

    # Determine shift + business date (configurable)
    computed_shift, business_date = resolve_shift_for_datetime(db, datetime.utcnow())
    if getattr(sale, "business_date", None) is not None:
        business_date = sale.business_date
    if sale.shift is not None:
        computed_shift = models.ShiftCode(sale.shift.value)

    tx_type = models.TransactionType(sale.transaction_type.value)

    total_dispensed = None
    sales_qty = None
    testing_qty = None
    computed_fuel_type = None
    computed_nozzle_id = sale.nozzle_id
    computed_product_id = None
    computed_tank_id = None
    opening_reading = None
    closing_reading = None
    meter = None

    operator_employee_id = getattr(sale, "operator_employee_id", None)
    if operator_employee_id is not None:
        employee = db.query(models.Employee).filter(models.Employee.id == operator_employee_id).first()
        if not employee:
            raise HTTPException(status_code=404, detail="Operator employee not found")
        if not employee.is_active:
            raise HTTPException(status_code=400, detail="Selected operator employee is inactive")

    deposit_cash = float(getattr(sale, "deposit_cash", 0.0) or 0.0)
    deposit_online = float(getattr(sale, "deposit_online", 0.0) or 0.0)
    if deposit_cash < 0 or deposit_online < 0:
        raise HTTPException(status_code=400, detail="Deposit amounts must be >= 0")

    if sale.meter_id is not None:
        meter = db.query(models.Meter).filter(models.Meter.id == sale.meter_id).first()
        if not meter:
            raise HTTPException(status_code=404, detail="Meter not found")
        if not meter.is_active:
            raise HTTPException(status_code=400, detail="Meter is not active")

        nozzle = db.query(models.Nozzle).filter(models.Nozzle.id == meter.nozzle_id).first()
        if not nozzle:
            raise HTTPException(status_code=400, detail="Meter is not linked to a valid nozzle")
        if nozzle.dispenser_id != sale.dispenser_id:
            raise HTTPException(status_code=400, detail="Meter/nozzle does not belong to selected dispenser")
        if not nozzle.is_active:
            raise HTTPException(status_code=400, detail="Nozzle is not active")

        if sale.nozzle_id is not None and sale.nozzle_id != nozzle.id:
            raise HTTPException(status_code=400, detail="Selected nozzle does not match meter")

        computed_nozzle_id = nozzle.id
        computed_fuel_type = nozzle.fuel_type
        computed_product_id = nozzle.product_id
        computed_tank_id = nozzle.tank_id

        if computed_product_id is None or computed_tank_id is None:
            raise HTTPException(status_code=400, detail="Nozzle must be configured with product_id and tank_id")

        product = db.query(models.Product).filter(models.Product.id == computed_product_id).first()
        if not product:
            raise HTTPException(status_code=400, detail="Nozzle product configuration is invalid")

        tank = db.query(models.Tank).filter(models.Tank.id == computed_tank_id).first()
        if not tank:
            raise HTTPException(status_code=400, detail="Nozzle tank configuration is invalid")
        if tank.product_id != product.id:
            raise HTTPException(status_code=400, detail="Nozzle tank product mismatch")

        if sale.closing_meter_reading is None:
            raise HTTPException(status_code=400, detail="closing_meter_reading is required when meter_id is provided")

        opening_reading = float(meter.last_reading or 0.0)
        closing_reading = float(sale.closing_meter_reading)

        if closing_reading < 0:
            raise HTTPException(status_code=400, detail="closing_meter_reading must be >= 0")

        if meter.max_value is not None:
            max_value = float(meter.max_value)
            if opening_reading > max_value or closing_reading > max_value:
                raise HTTPException(status_code=400, detail="Meter readings must be <= configured max_value")

            if closing_reading >= opening_reading:
                total_dispensed = closing_reading - opening_reading
            else:
                total_dispensed = (max_value - opening_reading) + closing_reading
        else:
            if closing_reading < opening_reading:
                raise HTTPException(status_code=400, detail="closing_meter_reading cannot be less than opening when max_value is not configured")
            total_dispensed = closing_reading - opening_reading

        if total_dispensed <= 0:
            raise HTTPException(status_code=400, detail="Computed sale quantity must be greater than 0")
    else:
        if sale.nozzle_id is None:
            raise HTTPException(status_code=400, detail="nozzle_id is required when meter_id is not provided")
        if sale.quantity is None or float(sale.quantity) <= 0:
            raise HTTPException(status_code=400, detail="quantity is required when meter_id is not provided")

        nozzle = db.query(models.Nozzle).filter(models.Nozzle.id == sale.nozzle_id).first()
        if not nozzle:
            raise HTTPException(status_code=404, detail="Nozzle not found")
        if nozzle.dispenser_id != sale.dispenser_id:
            raise HTTPException(status_code=400, detail="Nozzle does not belong to selected dispenser")
        if not nozzle.is_active:
            raise HTTPException(status_code=400, detail="Nozzle is not active")
        if nozzle.product_id is None:
            raise HTTPException(status_code=400, detail="Nozzle must be configured with product_id")

        computed_fuel_type = nozzle.fuel_type
        computed_product_id = nozzle.product_id
        computed_tank_id = nozzle.tank_id
        if tx_type == models.TransactionType.TESTING:
            total_dispensed = float(sale.quantity)
            testing_qty = total_dispensed
            sales_qty = 0.0
        else:
            sales_qty = float(sale.quantity)
            testing_qty = _coerce_testing_quantity(getattr(sale, "testing_quantity", None))
            total_dispensed = sales_qty + testing_qty

        if sale.fuel_type is not None and sale.fuel_type != computed_fuel_type:
            raise HTTPException(status_code=400, detail="Product category does not match nozzle product")

    if sale.meter_id is not None:
        testing_qty = _coerce_testing_quantity(getattr(sale, "testing_quantity", None))
        if total_dispensed is None:
            raise HTTPException(status_code=400, detail="Unable to compute dispensed quantity")
        if tx_type == models.TransactionType.TESTING:
            if testing_qty and abs(testing_qty - total_dispensed) > 1e-6:
                raise HTTPException(status_code=400, detail="Testing quantity must match dispensed quantity for testing entries")
            testing_qty = float(total_dispensed)
            sales_qty = 0.0
        else:
            if testing_qty > total_dispensed + 1e-6:
                raise HTTPException(status_code=400, detail="Testing quantity cannot exceed dispensed quantity")
            sales_qty = float(total_dispensed) - float(testing_qty)

    inventory = db.query(models.FuelInventory).filter(models.FuelInventory.fuel_type == computed_fuel_type).first()
    if not inventory:
        raise HTTPException(status_code=404, detail="Fuel type not found in inventory")

    resolved_price_per_liter = float(inventory.price_per_liter)
    if computed_product_id is not None:
        latest_price = (
            db.query(models.ProductPrice)
            .filter(models.ProductPrice.product_id == computed_product_id)
            .order_by(models.ProductPrice.effective_date.desc(), models.ProductPrice.created_at.desc())
            .first()
        )
        if latest_price is not None:
            resolved_price_per_liter = float(latest_price.price_per_liter)

    if tx_type == models.TransactionType.SALE and sales_qty is not None and inventory.current_stock < sales_qty:
        raise HTTPException(status_code=400, detail="Insufficient fuel stock")

    total_amount = 0.0 if tx_type == models.TransactionType.TESTING else ((sales_qty or 0.0) * resolved_price_per_liter)

    return {
        "business_date": business_date.isoformat(),
        "shift": computed_shift.value,
        "transaction_type": tx_type.value,
        "nozzle_id": computed_nozzle_id,
        "fuel_type": computed_fuel_type,
        "product_id": computed_product_id,
        "quantity": float(sales_qty or 0.0),
        "testing_quantity": float(testing_qty or 0.0),
        "dispensed_quantity": float((sales_qty or 0.0) + (testing_qty or 0.0)),
        "opening_meter_reading": opening_reading,
        "closing_meter_reading": closing_reading,
        "price_per_liter": float(resolved_price_per_liter),
        "total_amount": float(total_amount),
        "total_deposit": float(deposit_cash + deposit_online),
    }


@router.get("/deleted", response_model=List[schemas.DeletedSale])
def list_deleted_sales(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    return (
        db.query(models.DeletedSale)
        .order_by(models.DeletedSale.deleted_at.desc(), models.DeletedSale.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.delete("/deleted/{deleted_id}", status_code=status.HTTP_204_NO_CONTENT)
def purge_deleted_sale(
    deleted_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    row = db.query(models.DeletedSale).filter(models.DeletedSale.id == deleted_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Deleted sale record not found")
    db.delete(row)
    db.commit()
    return None


@router.post("/deleted/{deleted_id}/restore", response_model=schemas.Sale)
def restore_deleted_sale(
    deleted_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    row = db.query(models.DeletedSale).filter(models.DeletedSale.id == deleted_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Deleted sale record not found")

    existing = db.query(models.Sale).filter(models.Sale.transaction_id == row.transaction_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Sale with this transaction_id already exists")

    payload = {
        "transaction_id": row.transaction_id,
        "dispenser_id": row.dispenser_id,
        "sales_batch_id": row.sales_batch_id,
        "nozzle_id": row.nozzle_id,
        "meter_id": row.meter_id,
        "user_id": row.user_id,
        "operator_id": row.operator_id,
        "operator_employee_id": row.operator_employee_id,
        "customer_id": row.customer_id,
        "fuel_type": row.fuel_type,
        "product_id": row.product_id,
        "quantity": row.quantity,
        "testing_quantity": row.testing_quantity,
        "opening_meter_reading": row.opening_meter_reading,
        "closing_meter_reading": row.closing_meter_reading,
        "price_per_liter": row.price_per_liter,
        "total_amount": row.total_amount,
        "payment_method": "cash",
        "business_date": row.business_date,
        "deposit_cash": row.deposit_cash,
        "deposit_online": row.deposit_online,
        "total_deposit": row.total_deposit,
        "remarks": row.remarks,
        "transaction_type": row.transaction_type,
        "shift": row.shift,
        "created_at": row.created_at or datetime.utcnow(),
        "edited_at": row.edited_at,
        "edited_by_user_id": row.edited_by_user_id,
    }

    if row.sales_batch_id is not None:
        exists = db.query(models.SalesBatch).filter(models.SalesBatch.id == row.sales_batch_id).first()
        if not exists:
            payload["sales_batch_id"] = None

    if row.original_sale_id and not db.query(models.Sale).filter(models.Sale.id == row.original_sale_id).first():
        payload["id"] = row.original_sale_id

    sale = models.Sale(**payload)
    db.add(sale)
    db.delete(row)
    db.commit()
    db.refresh(sale)
    return sale

@router.get("/batches", response_model=List[schemas.SalesBatch])
def list_sales_batches(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access),
    business_date_from: Optional[date] = Query(None),
    business_date_to: Optional[date] = Query(None),
    shift: Optional[schemas.ShiftCode] = Query(None),
    dispenser_id: Optional[int] = Query(None),
    operator_employee_id: Optional[int] = Query(None),
    nozzle_id: Optional[int] = Query(None),
    meter_id: Optional[int] = Query(None),
    product_id: Optional[int] = Query(None),
):
    _ = current_user
    query = db.query(models.SalesBatch).options(joinedload(models.SalesBatch.lines))

    if business_date_from is not None:
        query = query.filter(models.SalesBatch.business_date >= business_date_from)
    if business_date_to is not None:
        query = query.filter(models.SalesBatch.business_date <= business_date_to)
    if shift is not None:
        query = query.filter(models.SalesBatch.shift == models.ShiftCode(shift.value))
    if dispenser_id is not None:
        query = query.filter(models.SalesBatch.dispenser_id == dispenser_id)
    if operator_employee_id is not None:
        query = query.filter(models.SalesBatch.operator_employee_id == operator_employee_id)
    if nozzle_id is not None or meter_id is not None or product_id is not None:
        query = query.join(models.SalesBatch.lines)
        if nozzle_id is not None:
            query = query.filter(models.Sale.nozzle_id == nozzle_id)
        if meter_id is not None:
            query = query.filter(models.Sale.meter_id == meter_id)
        if product_id is not None:
            query = query.filter(models.Sale.product_id == product_id)
        query = query.distinct()

    rows = (
        query.order_by(models.SalesBatch.business_date.desc(), models.SalesBatch.created_at.desc())
        .all()
    )
    for batch in rows:
        if batch.lines:
            batch.lines.sort(key=lambda s: (s.nozzle_id or 0, s.meter_id or 0, s.id))
    return rows


@router.post("/batches", response_model=schemas.SalesBatch, status_code=status.HTTP_201_CREATED)
def create_sales_batch(
    payload: schemas.SalesBatchCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    dispenser = db.query(models.Dispenser).filter(models.Dispenser.id == payload.dispenser_id).first()
    if not dispenser:
        raise HTTPException(status_code=404, detail="Dispenser not found")
    if not dispenser.is_active:
        raise HTTPException(status_code=400, detail="Dispenser is not active")

    computed_shift, business_date = resolve_shift_for_datetime(db, datetime.utcnow())
    if payload.business_date is not None:
        business_date = payload.business_date
    if payload.shift is not None:
        computed_shift = models.ShiftCode(payload.shift.value)

    _ensure_operator_employee(db, payload.operator_employee_id)

    deposit_cash = float(payload.deposit_cash or 0.0)
    deposit_online = float(payload.deposit_online or 0.0)
    deposit_credit = float(payload.deposit_credit or 0.0)
    if deposit_cash < 0 or deposit_online < 0 or deposit_credit < 0:
        raise HTTPException(status_code=400, detail="Deposit amounts must be >= 0")

    existing = (
        db.query(models.SalesBatch)
        .filter(
            models.SalesBatch.dispenser_id == payload.dispenser_id,
            models.SalesBatch.business_date == business_date,
            models.SalesBatch.shift == computed_shift,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Shift entry already exists for this dispenser, date, and shift")

    batch_code = f"BATCH{business_date.strftime('%Y%m%d')}{computed_shift.value}{uuid.uuid4().hex[:5].upper()}"
    credit_status = None
    if deposit_credit > 0:
        credit_status = models.CreditStatus.PENDING

    batch = models.SalesBatch(
        batch_code=batch_code,
        dispenser_id=payload.dispenser_id,
        business_date=business_date,
        shift=computed_shift,
        operator_employee_id=payload.operator_employee_id,
        user_id=current_user.id,
        deposit_cash=deposit_cash,
        deposit_online=deposit_online,
        deposit_credit=deposit_credit,
        total_deposit=float(deposit_cash + deposit_online),
        remarks=payload.remarks,
        credit_status=credit_status,
    )
    db.add(batch)
    db.flush()

    seen_meters: set[int] = set()
    seen_nozzles: set[int] = set()
    created_lines: List[models.Sale] = []

    for line in payload.lines:
        if (
            line.meter_id is None
            and line.nozzle_id is None
            and line.quantity is None
            and line.testing_quantity is None
            and line.closing_meter_reading is None
        ):
            continue
        created_lines.append(
            _create_sale_line_from_batch(
                line,
                batch=batch,
                db=db,
                current_user=current_user,
                seen_meters=seen_meters,
                seen_nozzles=seen_nozzles,
            )
        )

    if not created_lines:
        raise HTTPException(status_code=400, detail="At least one line is required for the shift entry")

    # Streamlined shift-close logic: one entry per dispenser+shift should cover
    # all active nozzles on that dispenser (even if dispensed quantity is 0).
    active_nozzles = (
        db.query(models.Nozzle)
        .filter(models.Nozzle.dispenser_id == payload.dispenser_id, models.Nozzle.is_active == True)  # noqa: E712
        .all()
    )
    required_nozzle_ids = {n.id for n in active_nozzles}
    missing_nozzle_ids = required_nozzle_ids - seen_nozzles
    if missing_nozzle_ids:
        missing_labels = []
        by_id = {n.id: n for n in active_nozzles}
        for nid in sorted(missing_nozzle_ids):
            n = by_id.get(nid)
            if n is None:
                missing_labels.append(str(nid))
            else:
                missing_labels.append(str(getattr(n, "nozzle_number", None) or n.id))
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Shift entry must include all active nozzles for this dispenser. Missing: {', '.join(missing_labels)}",
        )

    db.commit()
    db.refresh(batch)
    batch.lines = created_lines
    return batch


@router.put("/batches/{batch_id}", response_model=schemas.SalesBatch)
def update_sales_batch(
    batch_id: int,
    payload: schemas.SalesBatchUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access),
):
    batch = db.query(models.SalesBatch).filter(models.SalesBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Shift entry not found")

    if payload.operator_employee_id is not None:
        _ensure_operator_employee(db, payload.operator_employee_id)
        batch.operator_employee_id = payload.operator_employee_id

    if payload.deposit_cash is not None:
        batch.deposit_cash = float(payload.deposit_cash)
    if payload.deposit_online is not None:
        batch.deposit_online = float(payload.deposit_online)
    if payload.deposit_credit is not None:
        if float(payload.deposit_credit) < 0:
            raise HTTPException(status_code=400, detail="deposit_credit must be >= 0")
        batch.deposit_credit = float(payload.deposit_credit)
        if batch.deposit_credit <= 0:
            batch.credit_status = None
            batch.credit_settled_at = None
            batch.credit_settled_by_user_id = None
            batch.credit_notes = None
        elif batch.credit_status is None:
            batch.credit_status = models.CreditStatus.PENDING
    if payload.remarks is not None:
        batch.remarks = payload.remarks

    batch.total_deposit = float(batch.deposit_cash or 0.0) + float(batch.deposit_online or 0.0)
    batch.edited_at = datetime.utcnow()
    batch.edited_by_user_id = current_user.id

    db.commit()
    db.refresh(batch)
    return batch


@router.get("/credits", response_model=List[schemas.SalesCreditEntry])
def list_credit_entries(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access),
    business_date_from: Optional[date] = Query(None),
    business_date_to: Optional[date] = Query(None),
    status: Optional[schemas.CreditStatus] = Query(None),
    dispenser_id: Optional[int] = Query(None),
    operator_employee_id: Optional[int] = Query(None),
):
    _ = current_user
    query = db.query(models.SalesBatch).filter(models.SalesBatch.deposit_credit > 0)

    if business_date_from is not None:
        query = query.filter(models.SalesBatch.business_date >= business_date_from)
    if business_date_to is not None:
        query = query.filter(models.SalesBatch.business_date <= business_date_to)
    if dispenser_id is not None:
        query = query.filter(models.SalesBatch.dispenser_id == dispenser_id)
    if operator_employee_id is not None:
        query = query.filter(models.SalesBatch.operator_employee_id == operator_employee_id)
    if status is not None:
        status_value = models.CreditStatus(status.value)
        if status_value == models.CreditStatus.PENDING:
            query = query.filter(
                or_(
                    models.SalesBatch.credit_status == status_value,
                    models.SalesBatch.credit_status.is_(None),
                )
            )
        else:
            query = query.filter(models.SalesBatch.credit_status == status_value)

    return (
        query.order_by(models.SalesBatch.business_date.desc(), models.SalesBatch.created_at.desc())
        .all()
    )


@router.put("/credits/{batch_id}", response_model=schemas.SalesCreditEntry)
def update_credit_entry(
    batch_id: int,
    payload: schemas.SalesCreditUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access),
):
    batch = db.query(models.SalesBatch).filter(models.SalesBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Shift entry not found")
    if float(batch.deposit_credit or 0.0) <= 0:
        raise HTTPException(status_code=400, detail="This shift entry has no credit amount")

    status_value = models.CreditStatus(payload.credit_status.value)
    batch.credit_status = status_value

    if status_value == models.CreditStatus.SETTLED:
        batch.credit_settled_at = payload.credit_settled_at or datetime.utcnow()
        batch.credit_settled_by_user_id = current_user.id
    else:
        batch.credit_settled_at = None
        batch.credit_settled_by_user_id = None

    if payload.credit_notes is not None:
        batch.credit_notes = payload.credit_notes

    batch.edited_at = datetime.utcnow()
    batch.edited_by_user_id = current_user.id

    db.commit()
    db.refresh(batch)
    return batch

@router.post("/", response_model=schemas.Sale, status_code=status.HTTP_201_CREATED)
def create_sale(
    sale: schemas.SaleCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Create a new sale transaction"""

    if getattr(sale, "sales_batch_id", None) is not None:
        raise HTTPException(status_code=400, detail="Use shift entry to create grouped dispenser sales")
    
    # Check if dispenser exists and is active
    dispenser = db.query(models.Dispenser).filter(models.Dispenser.id == sale.dispenser_id).first()
    if not dispenser:
        raise HTTPException(status_code=404, detail="Dispenser not found")
    if not dispenser.is_active:
        raise HTTPException(status_code=400, detail="Dispenser is not active")

    # Determine shift + business date (configurable)
    computed_shift, business_date = resolve_shift_for_datetime(db, datetime.utcnow())
    # Allow explicit business_date / shift for shift-closing entry
    if getattr(sale, "business_date", None) is not None:
        business_date = sale.business_date
    if sale.shift is not None:
        computed_shift = models.ShiftCode(sale.shift.value)

    tx_type = models.TransactionType(sale.transaction_type.value)

    # Meter-based sale (preferred)
    total_dispensed = None
    sales_qty = None
    testing_qty = None
    computed_fuel_type = None
    computed_nozzle_id = sale.nozzle_id
    computed_product_id = None
    computed_tank_id = None
    opening_reading = None
    closing_reading = None
    meter = None

    # Shift-closing fields
    operator_employee_id = getattr(sale, "operator_employee_id", None)
    if operator_employee_id is not None:
        employee = db.query(models.Employee).filter(models.Employee.id == operator_employee_id).first()
        if not employee:
            raise HTTPException(status_code=404, detail="Operator employee not found")
        if not employee.is_active:
            raise HTTPException(status_code=400, detail="Selected operator employee is inactive")

    deposit_cash = float(getattr(sale, "deposit_cash", 0.0) or 0.0)
    deposit_online = float(getattr(sale, "deposit_online", 0.0) or 0.0)
    if deposit_cash < 0 or deposit_online < 0:
        raise HTTPException(status_code=400, detail="Deposit amounts must be >= 0")
    total_deposit = deposit_cash + deposit_online
    remarks = getattr(sale, "remarks", None)

    if sale.meter_id is not None:
        meter = db.query(models.Meter).filter(models.Meter.id == sale.meter_id).first()
        if not meter:
            raise HTTPException(status_code=404, detail="Meter not found")
        if not meter.is_active:
            raise HTTPException(status_code=400, detail="Meter is not active")

        nozzle = db.query(models.Nozzle).filter(models.Nozzle.id == meter.nozzle_id).first()
        if not nozzle:
            raise HTTPException(status_code=400, detail="Meter is not linked to a valid nozzle")
        if nozzle.dispenser_id != sale.dispenser_id:
            raise HTTPException(status_code=400, detail="Meter/nozzle does not belong to selected dispenser")
        if not nozzle.is_active:
            raise HTTPException(status_code=400, detail="Nozzle is not active")

        if sale.nozzle_id is not None and sale.nozzle_id != nozzle.id:
            raise HTTPException(status_code=400, detail="Selected nozzle does not match meter")

        computed_nozzle_id = nozzle.id
        computed_fuel_type = nozzle.fuel_type

        computed_product_id = nozzle.product_id
        computed_tank_id = nozzle.tank_id

        if computed_product_id is None or computed_tank_id is None:
            raise HTTPException(status_code=400, detail="Nozzle must be configured with product_id and tank_id")

        product = db.query(models.Product).filter(models.Product.id == computed_product_id).first()
        if not product:
            raise HTTPException(status_code=400, detail="Nozzle product configuration is invalid")

        tank = db.query(models.Tank).filter(models.Tank.id == computed_tank_id).first()
        if not tank:
            raise HTTPException(status_code=400, detail="Nozzle tank configuration is invalid")
        if tank.product_id != product.id:
            raise HTTPException(status_code=400, detail="Nozzle tank product mismatch")

        if sale.closing_meter_reading is None:
            raise HTTPException(status_code=400, detail="closing_meter_reading is required when meter_id is provided")

        opening_reading = float(meter.last_reading or 0.0)
        closing_reading = float(sale.closing_meter_reading)

        if closing_reading < 0:
            raise HTTPException(status_code=400, detail="closing_meter_reading must be >= 0")

        if meter.max_value is not None:
            max_value = float(meter.max_value)
            if opening_reading > max_value or closing_reading > max_value:
                raise HTTPException(status_code=400, detail="Meter readings must be <= configured max_value")

            if closing_reading >= opening_reading:
                total_dispensed = closing_reading - opening_reading
            else:
                # meter wrapped to 0 after hitting max_value
                total_dispensed = (max_value - opening_reading) + closing_reading
        else:
            if closing_reading < opening_reading:
                raise HTTPException(status_code=400, detail="closing_meter_reading cannot be less than opening when max_value is not configured")
            total_dispensed = closing_reading - opening_reading

        if total_dispensed <= 0:
            raise HTTPException(status_code=400, detail="Computed sale quantity must be greater than 0")

        # Prevent duplicate entry for the same meter in the same shift/business date.
        existing = (
            db.query(models.Sale)
            .filter(
                models.Sale.meter_id == meter.id,
                models.Sale.business_date == business_date,
                models.Sale.shift == computed_shift,
            )
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="A sale entry already exists for this meter, shift, and date")

    # Quantity-based sale (fallback)
    else:
        if sale.quantity is None or float(sale.quantity) <= 0:
            raise HTTPException(status_code=400, detail="quantity is required when meter_id is not provided")
        if sale.nozzle_id is None:
            raise HTTPException(status_code=400, detail="nozzle_id is required when meter_id is not provided")

        if tx_type == models.TransactionType.TESTING:
            total_dispensed = float(sale.quantity)
            testing_qty = total_dispensed
            sales_qty = 0.0
        else:
            sales_qty = float(sale.quantity)
            testing_qty = _coerce_testing_quantity(getattr(sale, "testing_quantity", None))
            total_dispensed = sales_qty + testing_qty

        computed_tank_id = None

        nozzle = db.query(models.Nozzle).filter(models.Nozzle.id == sale.nozzle_id).first()
        if not nozzle:
            raise HTTPException(status_code=404, detail="Nozzle not found")
        if nozzle.dispenser_id != sale.dispenser_id:
            raise HTTPException(status_code=400, detail="Nozzle does not belong to selected dispenser")
        if not nozzle.is_active:
            raise HTTPException(status_code=400, detail="Nozzle is not active")
        if nozzle.product_id is None:
            raise HTTPException(status_code=400, detail="Nozzle must be configured with product_id")

        computed_fuel_type = nozzle.fuel_type
        computed_product_id = nozzle.product_id
        computed_tank_id = nozzle.tank_id

        if sale.fuel_type is not None and sale.fuel_type != computed_fuel_type:
            raise HTTPException(status_code=400, detail="Product category does not match nozzle product")
    
    if sale.meter_id is not None:
        testing_qty = _coerce_testing_quantity(getattr(sale, "testing_quantity", None))
        if total_dispensed is None:
            raise HTTPException(status_code=400, detail="Unable to compute dispensed quantity")
        if tx_type == models.TransactionType.TESTING:
            if testing_qty and abs(testing_qty - total_dispensed) > 1e-6:
                raise HTTPException(status_code=400, detail="Testing quantity must match dispensed quantity for testing entries")
            testing_qty = float(total_dispensed)
            sales_qty = 0.0
        else:
            if testing_qty > total_dispensed + 1e-6:
                raise HTTPException(status_code=400, detail="Testing quantity cannot exceed dispensed quantity")
            sales_qty = float(total_dispensed) - float(testing_qty)

    # Get fuel inventory and check stock
    inventory = db.query(models.FuelInventory).filter(models.FuelInventory.fuel_type == computed_fuel_type).first()
    if not inventory:
        raise HTTPException(status_code=404, detail="Fuel type not found in inventory")

    # Resolve price: prefer latest product price, fallback to inventory price.
    resolved_price_per_liter = float(inventory.price_per_liter)
    if computed_product_id is not None:
        latest_price = (
            db.query(models.ProductPrice)
            .filter(models.ProductPrice.product_id == computed_product_id)
            .order_by(models.ProductPrice.effective_date.desc(), models.ProductPrice.created_at.desc())
            .first()
        )
        if latest_price is not None:
            resolved_price_per_liter = float(latest_price.price_per_liter)

    # Stock check only affects SALE (testing stays within station)
    if tx_type == models.TransactionType.SALE and sales_qty is not None and inventory.current_stock < sales_qty:
        raise HTTPException(status_code=400, detail="Insufficient fuel stock")
    
    # Calculate total amount
    total_amount = 0.0 if tx_type == models.TransactionType.TESTING else ((sales_qty or 0.0) * resolved_price_per_liter)
    
    # Generate transaction ID
    transaction_id = f"TXN{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"
    
    # Create sale
    db_sale = models.Sale(
        transaction_id=transaction_id,
            dispenser_id=sale.dispenser_id,
        nozzle_id=computed_nozzle_id,
        meter_id=sale.meter_id,
        user_id=current_user.id,
        fuel_type=computed_fuel_type,
        product_id=computed_product_id,
        quantity=float(sales_qty or 0.0),
        testing_quantity=float(testing_qty or 0.0),
        opening_meter_reading=opening_reading,
        closing_meter_reading=closing_reading,
        price_per_liter=resolved_price_per_liter,
        total_amount=total_amount,
        business_date=business_date,
        operator_employee_id=operator_employee_id,
        deposit_cash=deposit_cash,
        deposit_online=deposit_online,
        total_deposit=total_deposit,
        remarks=remarks,
        transaction_type=tx_type,
        shift=computed_shift,
        operator_id=current_user.id,
    )
    db.add(db_sale)

    # Tank + inventory handling
    nozzle_tank = None
    if computed_tank_id is not None:
        nozzle_tank = db.query(models.Tank).filter(models.Tank.id == computed_tank_id).first()
        if nozzle_tank is None:
            raise HTTPException(status_code=400, detail="Configured nozzle tank not found")
        if total_dispensed is None:
            raise HTTPException(status_code=400, detail="Unable to compute dispensed quantity")
        if float(nozzle_tank.current_volume or 0.0) < total_dispensed:
            raise HTTPException(status_code=400, detail="Insufficient tank volume")

        # Always decrement nozzle tank volume (fuel was dispensed)
        nozzle_tank.current_volume = float(nozzle_tank.current_volume or 0.0) - total_dispensed

    if tx_type == models.TransactionType.SALE and sales_qty is not None and sales_qty > 0:
        previous_stock = float(inventory.current_stock or 0.0)
        inventory.current_stock = previous_stock - float(sales_qty)
        inventory_log = models.InventoryLog(
            fuel_type=computed_fuel_type,
            action="sale",
            quantity=float(sales_qty),
            previous_stock=previous_stock,
            new_stock=inventory.current_stock,
            notes=f"Sale transaction: {transaction_id}",
        )
        db.add(inventory_log)
    # Testing quantity: move into buffer tank for the product.
    if (testing_qty or 0.0) > 0 and computed_product_id is not None and nozzle_tank is not None:
        product = db.query(models.Product).filter(models.Product.id == computed_product_id).first()
        if not product:
            raise HTTPException(status_code=400, detail="Product not found for testing")

        # Ensure buffer tank exists
        buffer_name = f"BUFFER-{product.product_name}".upper()
        buffer_tank = db.query(models.Tank).filter(models.Tank.tank_name == buffer_name).first()
        if not buffer_tank:
            buffer_tank = models.Tank(
                tank_name=buffer_name,
                product_id=product.id,
                capacity=10**12,
                current_volume=0.0,
                is_buffer=True,
                remarks="Auto-created buffer tank",
            )
            db.add(buffer_tank)
            db.flush()

        buffer_tank.current_volume = float(buffer_tank.current_volume or 0.0) + float(testing_qty)
        transfer = models.TankTransfer(
            from_tank_id=nozzle_tank.id,
            to_tank_id=buffer_tank.id,
            product_id=product.id,
            volume=float(testing_qty),
            transfer_type=models.TankTransferType.TESTING_TO_BUFFER,
            user_id=current_user.id,
        )
        db.add(transfer)

    # Update meter last_reading if meter-based sale
    if meter is not None:
        meter.last_reading = closing_reading
    
    db.commit()
    db.refresh(db_sale)
    return db_sale

@router.get("/", response_model=List[schemas.Sale])
def get_sales(
    skip: int = 0,
    limit: int = 100,
    business_date_from: Optional[date] = None,
    business_date_to: Optional[date] = None,
    shift: Optional[models.ShiftCode] = None,
    transaction_type: Optional[models.TransactionType] = None,
    has_testing: Optional[bool] = Query(None),
    operator_employee_id: Optional[int] = None,
    dispenser_id: Optional[int] = None,
    nozzle_id: Optional[int] = None,
    meter_id: Optional[int] = None,
    product_id: Optional[int] = None,
    sales_batch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access)
):
    """Get all sales with pagination"""
    query = db.query(models.Sale)

    # Prefer business_date filters when present; fallback to created_at date for legacy rows.
    if business_date_from is not None:
        df = business_date_from.isoformat()
        query = query.filter(
            (models.Sale.business_date >= business_date_from)
            | ((models.Sale.business_date.is_(None)) & (func.date(models.Sale.created_at) >= df))
        )
    if business_date_to is not None:
        dt = business_date_to.isoformat()
        query = query.filter(
            (models.Sale.business_date <= business_date_to)
            | ((models.Sale.business_date.is_(None)) & (func.date(models.Sale.created_at) <= dt))
        )

    if shift is not None:
        query = query.filter(models.Sale.shift == shift)
    if transaction_type is not None:
        query = query.filter(models.Sale.transaction_type == transaction_type)
    if has_testing is not None:
        testing_expr = or_(
            func.coalesce(models.Sale.testing_quantity, 0.0) > 0,
            models.Sale.transaction_type == models.TransactionType.TESTING,
        )
        query = query.filter(testing_expr if has_testing else ~testing_expr)
    if operator_employee_id is not None:
        query = query.filter(models.Sale.operator_employee_id == operator_employee_id)
    if dispenser_id is not None:
        query = query.filter(models.Sale.dispenser_id == dispenser_id)
    if nozzle_id is not None:
        query = query.filter(models.Sale.nozzle_id == nozzle_id)
    if meter_id is not None:
        query = query.filter(models.Sale.meter_id == meter_id)
    if product_id is not None:
        query = query.filter(models.Sale.product_id == product_id)
    if sales_batch_id is not None:
        query = query.filter(models.Sale.sales_batch_id == sales_batch_id)

    sales = query.order_by(models.Sale.created_at.desc()).offset(skip).limit(limit).all()
    return sales

@router.get("/{sale_id}", response_model=schemas.Sale)
def get_sale(
    sale_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access)
):
    """Get a specific sale by ID"""
    sale = db.query(models.Sale).filter(models.Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    return sale

@router.get("/transaction/{transaction_id}", response_model=schemas.Sale)
def get_sale_by_transaction(
    transaction_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access)
):
    """Get a sale by transaction ID"""
    sale = db.query(models.Sale).filter(models.Sale.transaction_id == transaction_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    return sale

@router.post("/{sale_id}/return-testing-to-main", response_model=schemas.TankTransfer, status_code=status.HTTP_201_CREATED)
def return_testing_to_main(
    sale_id: int,
    payload: schemas.TestingReturnToMainRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_manager_or_admin),
):
    sale = db.query(models.Sale).filter(models.Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    testing_qty = _testing_qty_from_sale(sale)
    if testing_qty <= 0:
        raise HTTPException(status_code=400, detail="No testing quantity recorded for this sale")

    if sale.product_id is None:
        raise HTTPException(status_code=400, detail="Testing transaction is missing product_id")

    product = db.query(models.Product).filter(models.Product.id == sale.product_id).first()
    if not product:
        raise HTTPException(status_code=400, detail="Testing transaction product not found")

    buffer_tank = (
        db.query(models.Tank)
        .filter(models.Tank.product_id == product.id, models.Tank.is_buffer == True)  # noqa: E712
        .order_by(models.Tank.id.asc())
        .first()
    )
    if not buffer_tank:
        raise HTTPException(status_code=400, detail="No buffer tank found for this product")

    to_tank = None
    if payload.to_tank_id is not None:
        to_tank = db.query(models.Tank).filter(models.Tank.id == payload.to_tank_id).first()
    else:
        # Best-effort: use configured nozzle tank if present.
        if sale.nozzle_id is not None:
            nozzle = db.query(models.Nozzle).filter(models.Nozzle.id == sale.nozzle_id).first()
            if nozzle and nozzle.tank_id is not None:
                to_tank = db.query(models.Tank).filter(models.Tank.id == nozzle.tank_id).first()

    if not to_tank:
        raise HTTPException(status_code=400, detail="Destination main tank is required")

    if bool(getattr(to_tank, "is_buffer", False)):
        raise HTTPException(status_code=400, detail="Destination tank must be a main tank")

    if int(to_tank.product_id) != int(product.id):
        raise HTTPException(status_code=400, detail="Destination tank product mismatch")

    volume = float(payload.volume)
    if volume <= 0:
        raise HTTPException(status_code=400, detail="Volume must be > 0")

    if float(buffer_tank.current_volume or 0.0) < volume:
        raise HTTPException(status_code=400, detail="Insufficient volume in buffer to return")

    if (float(to_tank.current_volume or 0.0) + volume) > float(to_tank.capacity or 0.0):
        raise HTTPException(status_code=400, detail="Destination tank capacity exceeded")

    buffer_tank.current_volume = float(buffer_tank.current_volume or 0.0) - volume
    to_tank.current_volume = float(to_tank.current_volume or 0.0) + volume

    transfer = models.TankTransfer(
        from_tank_id=buffer_tank.id,
        to_tank_id=to_tank.id,
        product_id=product.id,
        volume=volume,
        transfer_type=models.TankTransferType.BUFFER_TO_MAIN,
        user_id=current_user.id,
    )
    db.add(transfer)
    db.commit()
    db.refresh(transfer)
    return transfer


@router.put("/{sale_id}", response_model=schemas.Sale)
def update_sale(
    sale_id: int,
    update: schemas.SaleUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access),
):
    """Update a sale entry.

    Supported edits:
    - business_date, shift, operator_employee_id, deposits, remarks
    - meter-based: closing_meter_reading (quantity is recomputed)
    - manual: quantity

    Safety:
    - If meter_id is set, only the latest entry for that meter can be edited.
    """
    sale = db.query(models.Sale).filter(models.Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    if sale.sales_batch_id is not None:
        if (
            update.business_date is not None
            or update.shift is not None
            or update.operator_employee_id is not None
            or update.deposit_cash is not None
            or update.deposit_online is not None
            or update.remarks is not None
        ):
            raise HTTPException(status_code=400, detail="Batch-level fields must be edited on the shift entry")

    if update.business_date is not None:
        sale.business_date = update.business_date
    if update.shift is not None:
        sale.shift = models.ShiftCode(update.shift.value)

    if update.operator_employee_id is not None:
        employee = db.query(models.Employee).filter(models.Employee.id == update.operator_employee_id).first()
        if not employee:
            raise HTTPException(status_code=404, detail="Operator employee not found")
        if not employee.is_active:
            raise HTTPException(status_code=400, detail="Selected operator employee is inactive")
        sale.operator_employee_id = update.operator_employee_id

    if update.deposit_cash is not None:
        if float(update.deposit_cash) < 0:
            raise HTTPException(status_code=400, detail="deposit_cash must be >= 0")
        sale.deposit_cash = float(update.deposit_cash)
    if update.deposit_online is not None:
        if float(update.deposit_online) < 0:
            raise HTTPException(status_code=400, detail="deposit_online must be >= 0")
        sale.deposit_online = float(update.deposit_online)

    if update.remarks is not None:
        sale.remarks = update.remarks

    # Edit sales data
    old_sales_qty = _sales_qty_from_sale(sale)
    old_testing_qty = _testing_qty_from_sale(sale)
    old_total_dispensed = float(old_sales_qty + old_testing_qty)

    new_sales_qty = float(old_sales_qty)
    new_testing_qty = float(old_testing_qty)
    new_total_dispensed = float(old_total_dispensed)
    new_closing = sale.closing_meter_reading

    if sale.meter_id is not None:
        # Meter-based edits: allow closing_meter_reading + testing_quantity.
        if update.quantity is not None:
            raise HTTPException(status_code=400, detail="Cannot edit quantity directly for meter-based sales; edit closing_meter_reading instead")

        if update.closing_meter_reading is not None:
            meter = db.query(models.Meter).filter(models.Meter.id == sale.meter_id).first()
            if not meter:
                raise HTTPException(status_code=400, detail="Cannot edit: meter not found")

            latest_for_meter = (
                db.query(models.Sale)
                .filter(models.Sale.meter_id == sale.meter_id)
                .order_by(models.Sale.created_at.desc(), models.Sale.id.desc())
                .first()
            )
            if not latest_for_meter or latest_for_meter.id != sale.id:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot edit this entry because it is not the latest for the selected meter. Edit the most recent meter entry first.",
                )

            opening = float(sale.opening_meter_reading or 0.0)
            closing = float(update.closing_meter_reading)
            if closing < 0:
                raise HTTPException(status_code=400, detail="closing_meter_reading must be >= 0")

            if meter.max_value is not None:
                max_value = float(meter.max_value)
                if opening > max_value or closing > max_value:
                    raise HTTPException(status_code=400, detail="Meter readings must be <= configured max_value")
                if closing >= opening:
                    computed = closing - opening
                else:
                    computed = (max_value - opening) + closing
            else:
                if closing < opening:
                    raise HTTPException(status_code=400, detail="closing_meter_reading cannot be less than opening when max_value is not configured")
                computed = closing - opening

            if computed <= 0:
                raise HTTPException(status_code=400, detail="Computed sale quantity must be greater than 0")

            new_total_dispensed = float(computed)
            new_closing = closing

            # Update meter.last_reading
            meter.last_reading = closing

        if update.testing_quantity is not None:
            new_testing_qty = _coerce_testing_quantity(update.testing_quantity)

        if sale.transaction_type == models.TransactionType.TESTING:
            if new_testing_qty and abs(new_testing_qty - new_total_dispensed) > 1e-6:
                raise HTTPException(status_code=400, detail="Testing quantity must match dispensed quantity for testing entries")
            new_testing_qty = float(new_total_dispensed)
            new_sales_qty = 0.0
        else:
            if new_testing_qty > new_total_dispensed + 1e-6:
                raise HTTPException(status_code=400, detail="Testing quantity cannot exceed dispensed quantity")
            new_sales_qty = float(new_total_dispensed) - float(new_testing_qty)

    else:
        # Manual sales: allow quantity + testing_quantity edits.
        if update.closing_meter_reading is not None:
            raise HTTPException(status_code=400, detail="Cannot edit closing_meter_reading for manual sales")

        if sale.transaction_type == models.TransactionType.TESTING:
            if update.testing_quantity is not None:
                raise HTTPException(status_code=400, detail="Cannot edit testing_quantity directly for testing-only sales")
            if update.quantity is not None:
                new_total_dispensed = float(update.quantity)
            if new_total_dispensed <= 0:
                raise HTTPException(status_code=400, detail="quantity must be > 0")
            new_testing_qty = float(new_total_dispensed)
            new_sales_qty = 0.0
        else:
            if update.quantity is not None:
                new_sales_qty = float(update.quantity)
                if new_sales_qty <= 0:
                    raise HTTPException(status_code=400, detail="quantity must be > 0")
            if update.testing_quantity is not None:
                new_testing_qty = _coerce_testing_quantity(update.testing_quantity)
            new_total_dispensed = float(new_sales_qty + new_testing_qty)

    delta_total = float(new_total_dispensed - old_total_dispensed)
    delta_sales = float(new_sales_qty - old_sales_qty)
    delta_testing = float(new_testing_qty - old_testing_qty)

    if abs(delta_total) > 1e-9:
        # Adjust nozzle tank volume if mapping exists.
        if sale.nozzle_id is None:
            raise HTTPException(status_code=400, detail="Cannot edit quantity: nozzle_id missing")
        nozzle = db.query(models.Nozzle).filter(models.Nozzle.id == sale.nozzle_id).first()
        if not nozzle or nozzle.tank_id is None:
            raise HTTPException(status_code=400, detail="Cannot edit quantity: nozzle tank mapping is missing")
        tank = db.query(models.Tank).filter(models.Tank.id == nozzle.tank_id).first()
        if not tank:
            raise HTTPException(status_code=400, detail="Cannot edit quantity: tank not found")

        # Tank always decreases by total dispensed; apply delta.
        next_tank_volume = float(tank.current_volume or 0.0) - float(delta_total)
        if next_tank_volume < 0:
            raise HTTPException(status_code=400, detail="Insufficient tank volume for this edit")
        tank.current_volume = next_tank_volume

    if abs(delta_sales) > 1e-9 and sale.transaction_type == models.TransactionType.SALE:
        inv = db.query(models.FuelInventory).filter(models.FuelInventory.fuel_type == sale.fuel_type).first()
        if not inv:
            raise HTTPException(status_code=400, detail="Inventory record not found for this fuel type")
        next_stock = float(inv.current_stock or 0.0) - float(delta_sales)
        if next_stock < 0:
            raise HTTPException(status_code=400, detail="Insufficient inventory stock for this edit")
        prev_stock = float(inv.current_stock or 0.0)
        inv.current_stock = next_stock
        db.add(
            models.InventoryLog(
                fuel_type=sale.fuel_type,
                action="sale_edit",
                quantity=float(delta_sales),
                previous_stock=prev_stock,
                new_stock=next_stock,
                notes=f"Edited sale transaction: {sale.transaction_id}",
            )
        )

    if abs(delta_testing) > 1e-9 and sale.product_id is not None:
        product = db.query(models.Product).filter(models.Product.id == sale.product_id).first()
        if product:
            buffer_name = f"BUFFER-{product.product_name}".upper()
            buffer_tank = db.query(models.Tank).filter(models.Tank.tank_name == buffer_name).first()
            if buffer_tank is None and delta_testing > 0:
                buffer_tank = models.Tank(
                    tank_name=buffer_name,
                    product_id=product.id,
                    capacity=10**12,
                    current_volume=0.0,
                    is_buffer=True,
                    remarks="Auto-created buffer tank",
                )
                db.add(buffer_tank)
                db.flush()
            if buffer_tank is not None:
                next_buf = float(buffer_tank.current_volume or 0.0) + float(delta_testing)
                if next_buf < 0:
                    raise HTTPException(status_code=400, detail="Buffer tank volume would become negative for this edit")
                buffer_tank.current_volume = next_buf

    # Persist computed changes
    sale.quantity = float(new_sales_qty)
    sale.testing_quantity = float(new_testing_qty)
    if sale.meter_id is not None and update.closing_meter_reading is not None:
        sale.closing_meter_reading = new_closing

    if sale.transaction_type == models.TransactionType.SALE:
        sale.total_amount = float(sale.price_per_liter or 0.0) * float(sale.quantity or 0.0)
    else:
        sale.total_amount = 0.0

    # Recompute total_deposit
    sale.total_deposit = float(sale.deposit_cash or 0.0) + float(sale.deposit_online or 0.0)

    # Edit audit
    sale.edited_at = datetime.utcnow()
    sale.edited_by_user_id = current_user.id

    db.commit()
    db.refresh(sale)
    return sale


@router.delete("/{sale_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sale(
    sale_id: int,
    reason: Optional[str] = Query(None, max_length=200),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_manager_or_admin),
):
    """Soft-delete a sale: move to deleted_sales then remove from sales.

    Rules:
    - Reverts tank/inventory/buffer changes best-effort before removing.
    - If meter_id is set, meter.last_reading is recomputed from remaining sales.
    """

    sale = db.query(models.Sale).filter(models.Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    if current_user.role == models.UserRole.MANAGER:
        request = queue_deletion_request(
            db=db,
            target_type=models.DeletionTargetType.SALE,
            target_id=sale.id,
            requested_by=current_user,
            reason=reason,
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "status": "pending",
                "request_id": request.id,
                "message": "Deletion request sent for admin approval.",
            },
        )

    perform_sale_delete(sale=sale, reason=reason, db=db, current_user=current_user)
    db.commit()
    return None


def perform_sale_delete(
    *,
    sale: models.Sale,
    reason: Optional[str],
    db: Session,
    current_user: models.User,
) -> models.DeletedSale:
    sales_qty = float(_sales_qty_from_sale(sale))
    testing_qty = float(_testing_qty_from_sale(sale))
    total_dispensed = float(sales_qty + testing_qty)
    if total_dispensed < 0:
        raise HTTPException(status_code=400, detail="Invalid sale quantity")

    # Handle meter rollback.
    if sale.meter_id is not None:
        meter = db.query(models.Meter).filter(models.Meter.id == sale.meter_id).first()
        if not meter:
            raise HTTPException(status_code=400, detail="Cannot delete: meter not found")

        latest_remaining = (
            db.query(models.Sale)
            .filter(models.Sale.meter_id == sale.meter_id, models.Sale.id != sale.id)
            .order_by(models.Sale.created_at.desc(), models.Sale.id.desc())
            .first()
        )
        meter.last_reading = (
            float(latest_remaining.closing_meter_reading)
            if (latest_remaining and latest_remaining.closing_meter_reading is not None)
            else 0.0
        )

    # Revert tank volume (uses nozzle.tank_id mapping when present)
    if sale.nozzle_id is not None:
        nozzle = db.query(models.Nozzle).filter(models.Nozzle.id == sale.nozzle_id).first()
        if nozzle and nozzle.tank_id is not None:
            tank = db.query(models.Tank).filter(models.Tank.id == nozzle.tank_id).first()
            if tank is not None:
                tank.current_volume = float(tank.current_volume or 0.0) + total_dispensed

    # Revert fuel inventory stock only for SALE transactions
    if sale.transaction_type == models.TransactionType.SALE and sales_qty > 0:
        inventory = db.query(models.FuelInventory).filter(models.FuelInventory.fuel_type == sale.fuel_type).first()
        if inventory is not None:
            previous_stock = float(inventory.current_stock or 0.0)
            inventory.current_stock = previous_stock + sales_qty
            try:
                inventory_log = models.InventoryLog(
                    fuel_type=sale.fuel_type,
                    action="sale_delete",
                    quantity=sales_qty,
                    previous_stock=previous_stock,
                    new_stock=inventory.current_stock,
                    notes=f"Deleted sale transaction: {sale.transaction_id}",
                )
                db.add(inventory_log)
            except Exception:
                # InventoryLog may not exist in older schemas; keep deletion best-effort.
                pass

    # Testing: revert buffer tank (best-effort)
    if testing_qty > 0 and sale.product_id is not None:
        product = db.query(models.Product).filter(models.Product.id == sale.product_id).first()
        if product is not None:
            buffer_name = f"BUFFER-{product.product_name}".upper()
            buffer_tank = db.query(models.Tank).filter(models.Tank.tank_name == buffer_name).first()
            if buffer_tank is not None:
                next_buf = float(buffer_tank.current_volume or 0.0) - testing_qty
                if next_buf < 0:
                    raise HTTPException(status_code=400, detail="Cannot delete: buffer tank volume would become negative")
                buffer_tank.current_volume = next_buf

    delete_reason = reason.strip() if isinstance(reason, str) and reason.strip() else None
    deleted = models.DeletedSale(
        original_sale_id=sale.id,
        transaction_id=sale.transaction_id,
        dispenser_id=sale.dispenser_id,
        sales_batch_id=sale.sales_batch_id,
        nozzle_id=sale.nozzle_id,
        meter_id=sale.meter_id,
        user_id=sale.user_id,
        operator_id=sale.operator_id,
        operator_employee_id=sale.operator_employee_id,
        customer_id=sale.customer_id,
        fuel_type=sale.fuel_type,
        product_id=sale.product_id,
        quantity=sale.quantity,
        testing_quantity=testing_qty,
        opening_meter_reading=sale.opening_meter_reading,
        closing_meter_reading=sale.closing_meter_reading,
        price_per_liter=sale.price_per_liter,
        total_amount=sale.total_amount,
        business_date=sale.business_date,
        deposit_cash=sale.deposit_cash,
        deposit_online=sale.deposit_online,
        total_deposit=sale.total_deposit,
        remarks=sale.remarks,
        transaction_type=sale.transaction_type,
        shift=sale.shift,
        created_at=sale.created_at,
        edited_at=sale.edited_at,
        edited_by_user_id=sale.edited_by_user_id,
        deleted_at=datetime.utcnow(),
        deleted_by_user_id=current_user.id,
        delete_reason=delete_reason,
    )
    db.add(deleted)
    db.delete(sale)
    return deleted
