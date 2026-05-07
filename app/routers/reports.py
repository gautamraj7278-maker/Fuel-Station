from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from datetime import datetime, timedelta, date
from typing import Dict, Any, List, Optional
from app.database import get_db
from app import models
from app.routers.auth import require_ops_access

router = APIRouter()


@router.get("/sales-range")
def get_sales_range(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    product_id: Optional[int] = Query(None),
) -> Dict[str, Any]:
    """Get sales summary for a custom date range (inclusive).

    Notes:
    - Prefers business_date for shift-closing, falls back to created_at date for legacy rows.
    - Excludes TESTING transactions.
    """
    _ = current_user

    today = datetime.utcnow().date()
    if from_date is None and to_date is None:
        from_date = today
        to_date = today
    elif from_date is None:
        from_date = to_date
    elif to_date is None:
        to_date = from_date
    if from_date > to_date:
        from_date, to_date = to_date, from_date

    date_filter = (
        (models.Sale.business_date >= from_date) & (models.Sale.business_date <= to_date)
    ) | (
        (func.date(models.Sale.created_at) >= from_date) & (func.date(models.Sale.created_at) <= to_date)
    )
    sales_only = models.Sale.transaction_type == models.TransactionType.SALE

    sales_filters = [date_filter, sales_only]
    if product_id is not None:
        sales_filters.append(models.Sale.product_id == product_id)

    sales = (
        db.query(
            func.count(models.Sale.id).label("total_transactions"),
            func.sum(models.Sale.quantity).label("total_quantity"),
            func.sum(models.Sale.total_amount).label("total_revenue"),
        )
        .filter(*sales_filters)
        .first()
    )

    legacy_deposit = (
        db.query(
            func.sum(models.Sale.deposit_cash).label("deposit_cash"),
            func.sum(models.Sale.deposit_online).label("deposit_online"),
            func.sum(models.Sale.total_deposit).label("total_deposit"),
        )
        .filter(*sales_filters, models.Sale.sales_batch_id.is_(None))
        .first()
    )
    batch_deposit = None
    if product_id is None:
        batch_deposit = (
            db.query(
                func.sum(models.SalesBatch.deposit_cash).label("deposit_cash"),
                func.sum(models.SalesBatch.deposit_online).label("deposit_online"),
                func.sum(models.SalesBatch.deposit_credit).label("deposit_credit"),
                func.sum(models.SalesBatch.total_deposit).label("total_deposit"),
            )
            .filter(
                models.SalesBatch.business_date >= from_date,
                models.SalesBatch.business_date <= to_date,
            )
            .first()
        )

    deposit_cash = float((legacy_deposit.deposit_cash or 0.0) + (batch_deposit.deposit_cash or 0.0 if batch_deposit else 0.0))
    deposit_online = float((legacy_deposit.deposit_online or 0.0) + (batch_deposit.deposit_online or 0.0 if batch_deposit else 0.0))
    deposit_credit = float(batch_deposit.deposit_credit or 0.0) if batch_deposit else 0.0
    total_deposit = float((legacy_deposit.total_deposit or 0.0) + (batch_deposit.total_deposit or 0.0 if batch_deposit else 0.0))
    total_accounted = float(total_deposit + deposit_credit)

    sales_by_fuel = (
        db.query(
            models.Sale.fuel_type,
            func.sum(models.Sale.quantity).label("quantity"),
            func.sum(models.Sale.total_amount).label("revenue"),
            func.sum(models.Sale.total_deposit).label("deposit"),
        )
        .filter(*sales_filters, models.Sale.sales_batch_id.is_(None))
        .group_by(models.Sale.fuel_type)
        .all()
    )

    dispenser_sales = (
        db.query(
            models.Dispenser.dispenser_number,
            models.Nozzle.nozzle_number,
            models.Product.product_name,
            models.Product.fuel_type,
            func.count(models.Sale.id).label("transactions"),
            func.sum(models.Sale.quantity).label("quantity"),
            func.sum(models.Sale.total_amount).label("revenue"),
            func.sum(models.Sale.total_deposit).label("deposit"),
        )
        .join(models.Sale, models.Dispenser.id == models.Sale.dispenser_id)
        .outerjoin(models.Nozzle, models.Nozzle.id == models.Sale.nozzle_id)
        .outerjoin(models.Product, models.Product.id == models.Sale.product_id)
        .filter(*sales_filters, models.Sale.sales_batch_id.is_(None))
        .group_by(
            models.Dispenser.dispenser_number,
            models.Nozzle.nozzle_number,
            models.Product.product_name,
            models.Product.fuel_type,
        )
        .order_by(models.Dispenser.dispenser_number.asc(), models.Nozzle.nozzle_number.asc())
        .all()
    )

    return {
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "total_transactions": sales.total_transactions or 0,
        "total_quantity": float(sales.total_quantity or 0),
        "total_revenue": float(sales.total_revenue or 0),
        "deposit_cash": deposit_cash,
        "deposit_online": deposit_online,
        "deposit_credit": deposit_credit,
        "total_deposit": total_deposit,
        "total_accounted": total_accounted,
        "by_fuel_type": [
            {
                "fuel_type": item.fuel_type,
                "quantity": float(item.quantity or 0),
                "revenue": float(item.revenue or 0),
                "deposit": float(item.deposit or 0),
            }
            for item in sales_by_fuel
        ],
        "dispenser_performance": [
            {
                "dispenser_number": item.dispenser_number,
                "nozzle_number": item.nozzle_number,
                "product_name": item.product_name,
                "fuel_type": item.fuel_type,
                "transactions": item.transactions or 0,
                "quantity": float(item.quantity or 0),
                "revenue": float(item.revenue or 0),
                "deposit": float(item.deposit or 0),
            }
            for item in dispenser_sales
        ],
    }

@router.get("/daily-sales")
def get_daily_sales(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access)
) -> Dict[str, Any]:
    """Get today's sales summary"""
    today = datetime.utcnow().date()

    # Prefer business_date for shift-closing, fallback to created_at date for legacy rows.
    # Exclude TESTING so sales values aren't polluted by meter-driven testing volume.
    date_filter = ((models.Sale.business_date == today) | (func.date(models.Sale.created_at) == today))
    sales_only = models.Sale.transaction_type == models.TransactionType.SALE
    
    sales = db.query(
        func.count(models.Sale.id).label("total_transactions"),
        func.sum(models.Sale.quantity).label("total_quantity"),
        func.sum(models.Sale.total_amount).label("total_revenue"),
    ).filter(
        date_filter,
        sales_only,
    ).first()

    legacy_deposit = (
        db.query(
            func.sum(models.Sale.deposit_cash).label("deposit_cash"),
            func.sum(models.Sale.deposit_online).label("deposit_online"),
            func.sum(models.Sale.total_deposit).label("total_deposit"),
        )
        .filter(date_filter, sales_only, models.Sale.sales_batch_id.is_(None))
        .first()
    )
    batch_deposit = (
        db.query(
            func.sum(models.SalesBatch.deposit_cash).label("deposit_cash"),
            func.sum(models.SalesBatch.deposit_online).label("deposit_online"),
            func.sum(models.SalesBatch.deposit_credit).label("deposit_credit"),
            func.sum(models.SalesBatch.total_deposit).label("total_deposit"),
        )
        .filter(models.SalesBatch.business_date == today)
        .first()
    )

    deposit_cash = float((legacy_deposit.deposit_cash or 0.0) + (batch_deposit.deposit_cash or 0.0))
    deposit_online = float((legacy_deposit.deposit_online or 0.0) + (batch_deposit.deposit_online or 0.0))
    deposit_credit = float(batch_deposit.deposit_credit or 0.0)
    total_deposit = float((legacy_deposit.total_deposit or 0.0) + (batch_deposit.total_deposit or 0.0))
    total_accounted = float(total_deposit + deposit_credit)
    
    # Sales by fuel type
    sales_by_fuel = db.query(
        models.Sale.fuel_type,
        func.sum(models.Sale.quantity).label("quantity"),
        func.sum(models.Sale.total_amount).label("revenue"),
        func.sum(models.Sale.total_deposit).label("deposit"),
    ).filter(
        date_filter,
        sales_only,
        models.Sale.sales_batch_id.is_(None),
    ).group_by(models.Sale.fuel_type).all()
    
    return {
        "date": today.isoformat(),
        "total_transactions": sales.total_transactions or 0,
        "total_quantity": float(sales.total_quantity or 0),
        "total_revenue": float(sales.total_revenue or 0),
        "deposit_cash": deposit_cash,
        "deposit_online": deposit_online,
        "deposit_credit": deposit_credit,
        "total_deposit": total_deposit,
        "total_accounted": total_accounted,
        "by_fuel_type": [
            {
                "fuel_type": item.fuel_type,
                "quantity": float(item.quantity),
                "revenue": float(item.revenue),
                "deposit": float(item.deposit or 0),
            }
            for item in sales_by_fuel
        ]
    }

@router.get("/weekly-sales")
def get_weekly_sales(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access)
) -> Dict[str, Any]:
    """Get this week's sales summary"""
    today = datetime.utcnow().date()
    week_start = today - timedelta(days=today.weekday())

    date_filter = (models.Sale.business_date >= week_start) | (func.date(models.Sale.created_at) >= week_start)
    sales_only = models.Sale.transaction_type == models.TransactionType.SALE
    
    sales = db.query(
        func.count(models.Sale.id).label("total_transactions"),
        func.sum(models.Sale.quantity).label("total_quantity"),
        func.sum(models.Sale.total_amount).label("total_revenue"),
    ).filter(
        date_filter,
        sales_only,
    ).first()

    legacy_deposit = (
        db.query(
            func.sum(models.Sale.deposit_cash).label("deposit_cash"),
            func.sum(models.Sale.deposit_online).label("deposit_online"),
            func.sum(models.Sale.total_deposit).label("total_deposit"),
        )
        .filter(date_filter, sales_only, models.Sale.sales_batch_id.is_(None))
        .first()
    )
    batch_deposit = (
        db.query(
            func.sum(models.SalesBatch.deposit_cash).label("deposit_cash"),
            func.sum(models.SalesBatch.deposit_online).label("deposit_online"),
            func.sum(models.SalesBatch.deposit_credit).label("deposit_credit"),
            func.sum(models.SalesBatch.total_deposit).label("total_deposit"),
        )
        .filter(
            models.SalesBatch.business_date >= week_start,
            models.SalesBatch.business_date <= today,
        )
        .first()
    )

    deposit_cash = float((legacy_deposit.deposit_cash or 0.0) + (batch_deposit.deposit_cash or 0.0))
    deposit_online = float((legacy_deposit.deposit_online or 0.0) + (batch_deposit.deposit_online or 0.0))
    deposit_credit = float(batch_deposit.deposit_credit or 0.0)
    total_deposit = float((legacy_deposit.total_deposit or 0.0) + (batch_deposit.total_deposit or 0.0))
    total_accounted = float(total_deposit + deposit_credit)
    
    return {
        "week_start": week_start.isoformat(),
        "week_end": today.isoformat(),
        "total_transactions": sales.total_transactions or 0,
        "total_quantity": float(sales.total_quantity or 0),
        "total_revenue": float(sales.total_revenue or 0),
        "deposit_cash": deposit_cash,
        "deposit_online": deposit_online,
        "deposit_credit": deposit_credit,
        "total_deposit": total_deposit,
        "total_accounted": total_accounted,
    }

@router.get("/monthly-sales")
def get_monthly_sales(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access)
) -> Dict[str, Any]:
    """Get this month's sales summary"""
    today = datetime.utcnow().date()
    month_start = today.replace(day=1)

    date_filter = (models.Sale.business_date >= month_start) | (func.date(models.Sale.created_at) >= month_start)
    sales_only = models.Sale.transaction_type == models.TransactionType.SALE
    
    sales = db.query(
        func.count(models.Sale.id).label("total_transactions"),
        func.sum(models.Sale.quantity).label("total_quantity"),
        func.sum(models.Sale.total_amount).label("total_revenue"),
    ).filter(
        date_filter,
        sales_only,
    ).first()

    legacy_deposit = (
        db.query(
            func.sum(models.Sale.deposit_cash).label("deposit_cash"),
            func.sum(models.Sale.deposit_online).label("deposit_online"),
            func.sum(models.Sale.total_deposit).label("total_deposit"),
        )
        .filter(date_filter, sales_only, models.Sale.sales_batch_id.is_(None))
        .first()
    )
    batch_deposit = (
        db.query(
            func.sum(models.SalesBatch.deposit_cash).label("deposit_cash"),
            func.sum(models.SalesBatch.deposit_online).label("deposit_online"),
            func.sum(models.SalesBatch.deposit_credit).label("deposit_credit"),
            func.sum(models.SalesBatch.total_deposit).label("total_deposit"),
        )
        .filter(
            models.SalesBatch.business_date >= month_start,
            models.SalesBatch.business_date <= today,
        )
        .first()
    )

    deposit_cash = float((legacy_deposit.deposit_cash or 0.0) + (batch_deposit.deposit_cash or 0.0))
    deposit_online = float((legacy_deposit.deposit_online or 0.0) + (batch_deposit.deposit_online or 0.0))
    deposit_credit = float(batch_deposit.deposit_credit or 0.0)
    total_deposit = float((legacy_deposit.total_deposit or 0.0) + (batch_deposit.total_deposit or 0.0))
    total_accounted = float(total_deposit + deposit_credit)
    
    return {
        "month_start": month_start.isoformat(),
        "month_end": today.isoformat(),
        "total_transactions": sales.total_transactions or 0,
        "total_quantity": float(sales.total_quantity or 0),
        "total_revenue": float(sales.total_revenue or 0),
        "deposit_cash": deposit_cash,
        "deposit_online": deposit_online,
        "deposit_credit": deposit_credit,
        "total_deposit": total_deposit,
        "total_accounted": total_accounted,
    }

@router.get("/inventory-status")
def get_inventory_status(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access)
) -> List[Dict[str, Any]]:
    """Get current inventory status with alerts"""
    _ = current_user
    inventory = db.query(models.FuelInventory).all()
    tank_totals = {
        fuel_type: float(total or 0.0)
        for fuel_type, total in (
            db.query(models.Product.fuel_type, func.sum(models.Tank.current_volume))
            .join(models.Tank, models.Tank.product_id == models.Product.id)
            .filter(models.Tank.is_buffer == False)  # noqa: E712
            .group_by(models.Product.fuel_type)
            .all()
        )
        if fuel_type is not None
    }

    return [
        {
            "fuel_type": item.fuel_type,
            "current_stock": float(tank_totals.get(item.fuel_type, 0.0)), # Always use tank totals as source of truth
            "reorder_level": float(item.reorder_level or 0),
            "price_per_liter": float(item.price_per_liter or 0),
            "needs_reorder": float(tank_totals.get(item.fuel_type, 0.0)) <= float(item.reorder_level or 0),
            "last_updated": item.last_updated.isoformat() if item.last_updated else None,
        }
        for item in inventory
    ]


@router.get("/tanker-receipts-range")
def tanker_receipts_range(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    product_id: Optional[int] = Query(None),
) -> Dict[str, Any]:
    _ = current_user

    today = datetime.utcnow().date()
    if from_date is None and to_date is None:
        from_date = today
        to_date = today
    elif from_date is None:
        from_date = to_date
    elif to_date is None:
        to_date = from_date
    if from_date > to_date:
        from_date, to_date = to_date, from_date

    date_filter = (models.TankerReceipt.receipt_date >= from_date) & (models.TankerReceipt.receipt_date <= to_date)

    invoice_query = (
        db.query(
            models.TankerReceiptCompartment.product_id,
            func.sum(models.TankerReceiptCompartment.quantity_invoice_litres).label("invoice_qty"),
        )
        .join(models.TankerReceipt, models.TankerReceipt.id == models.TankerReceiptCompartment.receipt_id)
        .filter(date_filter, models.TankerReceipt.status == models.TankerReceiptStatus.CONFIRMED)
        .group_by(models.TankerReceiptCompartment.product_id)
    )

    if product_id is not None:
        invoice_query = invoice_query.filter(models.TankerReceiptCompartment.product_id == product_id)

    invoice_rows = invoice_query.all()

    received_query = (
        db.query(
            models.TankerReceiptLine.product_id,
            func.sum(models.TankerReceiptLine.received_volume_litres).label("received_qty"),
        )
        .join(models.TankerReceipt, models.TankerReceipt.id == models.TankerReceiptLine.receipt_id)
        .filter(date_filter, models.TankerReceipt.status == models.TankerReceiptStatus.CONFIRMED)
        .group_by(models.TankerReceiptLine.product_id)
    )

    if product_id is not None:
        received_query = received_query.filter(models.TankerReceiptLine.product_id == product_id)

    received_rows = received_query.all()

    by_product: dict[int, Dict[str, Any]] = {}
    for r in invoice_rows:
        by_product[int(r.product_id)] = {
            "product_id": int(r.product_id),
            "invoice_qty": float(r.invoice_qty or 0),
            "received_qty": 0.0,
        }
    for r in received_rows:
        pid = int(r.product_id)
        if pid not in by_product:
            by_product[pid] = {"product_id": pid, "invoice_qty": 0.0, "received_qty": 0.0}
        by_product[pid]["received_qty"] = float(r.received_qty or 0)

    # enrich with product name/fuel_type
    product_ids = list(by_product.keys())
    products = []
    if product_ids:
        products = db.query(models.Product).filter(models.Product.id.in_(product_ids)).all()
    product_map = {p.id: p for p in products}

    result = []
    for pid, item in by_product.items():
        p = product_map.get(pid)
        invoice_qty = float(item["invoice_qty"])
        received_qty = float(item["received_qty"])
        result.append(
            {
                "product_id": pid,
                "product_name": getattr(p, "product_name", None),
                "fuel_type": getattr(p, "fuel_type", None),
                "invoice_qty": invoice_qty,
                "received_qty": received_qty,
                "difference_qty": received_qty - invoice_qty,
            }
        )

    result.sort(key=lambda x: (str(x.get("product_name") or ""), int(x.get("product_id") or 0)))

    return {
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "by_product": result,
    }


@router.get("/mass-balance-range")
def mass_balance_range(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    product_id: Optional[int] = Query(None),
) -> Dict[str, Any]:
    _ = current_user

    today = datetime.utcnow().date()
    if from_date is None and to_date is None:
        from_date = today
        to_date = today
    elif from_date is None:
        from_date = to_date
    elif to_date is None:
        to_date = from_date
    if from_date > to_date:
        from_date, to_date = to_date, from_date

    # Pre-load products referenced by tanks.
    products = db.query(models.Product).order_by(models.Product.product_name.asc()).all()
    product_map = {p.id: p for p in products}

    # Helper SQL expression: prefer manual volume override.
    dip_volume = func.coalesce(models.TankDipReading.manual_volume_litres, models.TankDipReading.computed_volume_litres)

    # Opening stock (main tanks) per day/product
    opening_main_query = (
        db.query(
            models.TankDipReading.business_date.label("business_date"),
            models.Tank.product_id.label("product_id"),
            func.sum(dip_volume).label("opening_stock"),
        )
        .join(models.Tank, models.Tank.id == models.TankDipReading.tank_id)
        .filter(
            models.TankDipReading.business_date >= from_date,
            models.TankDipReading.business_date <= to_date,
            models.TankDipReading.dip_type == models.TankDipType.OPENING,
            models.Tank.is_buffer == False,
        )
        .group_by(models.TankDipReading.business_date, models.Tank.product_id)
    )

    if product_id is not None:
        opening_main_query = opening_main_query.filter(models.Tank.product_id == product_id)

    opening_main_rows = opening_main_query.all()

    # Buffer is virtual: compute balances from transfers (TESTING_TO_BUFFER and BUFFER_TO_MAIN).
    transfer_date = func.date(models.TankTransfer.created_at)

    # Physical closing (main tanks) per day/product
    closing_main_query = (
        db.query(
            models.TankDipReading.business_date.label("business_date"),
            models.Tank.product_id.label("product_id"),
            func.sum(dip_volume).label("physical_closing_stock"),
        )
        .join(models.Tank, models.Tank.id == models.TankDipReading.tank_id)
        .filter(
            models.TankDipReading.business_date >= from_date,
            models.TankDipReading.business_date <= to_date,
            models.TankDipReading.dip_type == models.TankDipType.CLOSING,
            models.Tank.is_buffer == False,
        )
        .group_by(models.TankDipReading.business_date, models.Tank.product_id)
    )

    if product_id is not None:
        closing_main_query = closing_main_query.filter(models.Tank.product_id == product_id)

    closing_main_rows = closing_main_query.all()

    # Transfers per day/product (in=TESTING_TO_BUFFER, out=BUFFER_TO_MAIN)
    transfers_query = (
        db.query(
            transfer_date.label("business_date"),
            models.TankTransfer.product_id.label("product_id"),
            func.sum(
                case(
                    (models.TankTransfer.transfer_type == models.TankTransferType.TESTING_TO_BUFFER, models.TankTransfer.volume),
                    else_=0.0,
                )
            ).label("testing_to_buffer"),
            func.sum(
                case(
                    (models.TankTransfer.transfer_type == models.TankTransferType.BUFFER_TO_MAIN, models.TankTransfer.volume),
                    else_=0.0,
                )
            ).label("buffer_to_main"),
        )
        .filter(
            transfer_date >= from_date,
            transfer_date <= to_date,
        )
        .group_by(transfer_date, models.TankTransfer.product_id)
    )
    if product_id is not None:
        transfers_query = transfers_query.filter(models.TankTransfer.product_id == product_id)
    transfer_rows = transfers_query.all()

    # Initial buffer balance before from_date (running sum start)
    init_buffer_query = (
        db.query(
            models.TankTransfer.product_id.label("product_id"),
            func.sum(
                case(
                    (models.TankTransfer.transfer_type == models.TankTransferType.TESTING_TO_BUFFER, models.TankTransfer.volume),
                    (models.TankTransfer.transfer_type == models.TankTransferType.BUFFER_TO_MAIN, -models.TankTransfer.volume),
                    else_=0.0,
                )
            ).label("balance"),
        )
        .filter(transfer_date < from_date)
        .group_by(models.TankTransfer.product_id)
    )
    if product_id is not None:
        init_buffer_query = init_buffer_query.filter(models.TankTransfer.product_id == product_id)
    init_buffer_rows = init_buffer_query.all()

    # Receipts (confirmed tanker offloading) main tanks only (deliveries never go to virtual buffer)
    receipt_main_query = (
        db.query(
            models.TankerReceipt.receipt_date.label("business_date"),
            models.TankerReceiptLine.product_id.label("product_id"),
            func.sum(models.TankerReceiptLine.received_volume_litres).label("receipt_qty"),
        )
        .join(models.TankerReceipt, models.TankerReceipt.id == models.TankerReceiptLine.receipt_id)
        .join(models.Tank, models.Tank.id == models.TankerReceiptLine.tank_id)
        .filter(
            models.TankerReceipt.receipt_date >= from_date,
            models.TankerReceipt.receipt_date <= to_date,
            models.TankerReceipt.status == models.TankerReceiptStatus.CONFIRMED,
            models.Tank.is_buffer == False,
        )
        .group_by(models.TankerReceipt.receipt_date, models.TankerReceiptLine.product_id)
    )

    if product_id is not None:
        receipt_main_query = receipt_main_query.filter(models.TankerReceiptLine.product_id == product_id)

    receipt_main_rows = receipt_main_query.all()

    receipt_buffer_rows = []

    # Sales (exclude testing), per day/product.
    sale_date = func.coalesce(models.Sale.business_date, func.date(models.Sale.created_at))
    sales_query = (
        db.query(
            sale_date.label("business_date"),
            models.Sale.product_id.label("product_id"),
            func.sum(models.Sale.quantity).label("sales_qty"),
        )
        .filter(
            sale_date >= from_date,
            sale_date <= to_date,
            models.Sale.transaction_type == models.TransactionType.SALE,
            models.Sale.product_id.isnot(None),
        )
        .group_by(sale_date, models.Sale.product_id)
    )

    if product_id is not None:
        sales_query = sales_query.filter(models.Sale.product_id == product_id)

    sales_rows = sales_query.all()

    # Index everything into dicts for easy assembly
    def _key(d, pid):
        return (str(d), int(pid))

    opening_main_map = {_key(r.business_date, r.product_id): float(r.opening_stock or 0) for r in opening_main_rows}
    closing_main_map = {_key(r.business_date, r.product_id): float(r.physical_closing_stock or 0) for r in closing_main_rows}
    receipt_main_map = {_key(r.business_date, r.product_id): float(r.receipt_qty or 0) for r in receipt_main_rows}
    receipt_buffer_map = {}
    sales_map = {_key(r.business_date, r.product_id): float(r.sales_qty or 0) for r in sales_rows}

    testing_to_buffer_map = {_key(r.business_date, r.product_id): float(r.testing_to_buffer or 0) for r in transfer_rows}
    buffer_to_main_map = {_key(r.business_date, r.product_id): float(r.buffer_to_main or 0) for r in transfer_rows}

    init_buffer_map = {int(r.product_id): float(r.balance or 0.0) for r in init_buffer_rows}

    # Determine the set of day/product combos to output.
    combos = (
        set(opening_main_map.keys())
        | set(closing_main_map.keys())
        | set(receipt_main_map.keys())
        | set(sales_map.keys())
        | set(testing_to_buffer_map.keys())
        | set(buffer_to_main_map.keys())
    )

    # Compute running buffer balances per product/day.
    rows: List[Dict[str, Any]] = []
    running_buffer: Dict[int, float] = {int(pid): float(bal) for pid, bal in init_buffer_map.items()}

    for d_str, pid in sorted(combos, key=lambda x: (x[0], x[1])):
        opening_main = float(opening_main_map.get((d_str, pid), 0.0))
        receipt_main = float(receipt_main_map.get((d_str, pid), 0.0))
        receipt_buffer = 0.0
        receipt_total = receipt_main

        sales_qty = float(sales_map.get((d_str, pid), 0.0))
        testing_to_buffer = float(testing_to_buffer_map.get((d_str, pid), 0.0))
        buffer_to_main = float(buffer_to_main_map.get((d_str, pid), 0.0))

        buffer_opening = float(running_buffer.get(pid, 0.0))
        buffer_closing = float(buffer_opening + testing_to_buffer - buffer_to_main)
        running_buffer[pid] = buffer_closing

        # Main book closing: opening + receipt - sales - testing_out + buffer_return
        book_main_closing = float(opening_main + receipt_main - sales_qty - testing_to_buffer + buffer_to_main)
        # Total book closing considers that buffer is physically on-site but not in tanks.
        book_total_closing = float(book_main_closing + buffer_closing)

        closing_main = float(closing_main_map.get((d_str, pid), 0.0))
        # Buffer is virtual: treat its balance as the physical amount outside the tank.
        closing_buffer = float(buffer_closing)
        physical_total = float(closing_main + closing_buffer)

        variance = float(physical_total - book_total_closing)

        p = product_map.get(pid)
        rows.append(
            {
                "date": d_str,
                "product_id": pid,
                "product_name": getattr(p, "product_name", None),
                "fuel_type": getattr(p, "fuel_type", None),
                "main_opening_stock": opening_main,
                "buffer_opening_stock": buffer_opening,
                "receipt_main": receipt_main,
                "receipt_buffer": receipt_buffer,
                "receipt": receipt_total,
                # Keep legacy key for UI: treat deliveries as SALES.
                "deliveries": sales_qty,
                "sales": sales_qty,
                "testings": testing_to_buffer,
                "buffer_to_main": buffer_to_main,
                "book_closing_stock": book_total_closing,
                "main_physical_closing_stock": closing_main,
                "buffer_physical_closing_stock": closing_buffer,
                "physical_closing_stock": physical_total,
                "variance": variance,
            }
        )

    return {
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "rows": rows,
    }

@router.get("/dispenser-performance")
@router.get("/pump-performance")
def get_dispenser_performance(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access)
) -> List[Dict[str, Any]]:
    """Get sales performance by dispenser"""
    today = datetime.utcnow().date()
    
    dispenser_sales = (
        db.query(
            models.Dispenser.dispenser_number,
            models.Nozzle.nozzle_number,
            models.Product.product_name,
            models.Product.fuel_type,
            func.count(models.Sale.id).label("transactions"),
            func.sum(models.Sale.quantity).label("quantity"),
            func.sum(models.Sale.total_amount).label("revenue"),
        )
        .join(models.Sale, models.Dispenser.id == models.Sale.dispenser_id)
        .outerjoin(models.Nozzle, models.Nozzle.id == models.Sale.nozzle_id)
        .outerjoin(models.Product, models.Product.id == models.Sale.product_id)
        .filter(
            func.date(models.Sale.created_at) == today,
            models.Sale.transaction_type == models.TransactionType.SALE,
        )
        .group_by(
            models.Dispenser.dispenser_number,
            models.Nozzle.nozzle_number,
            models.Product.product_name,
            models.Product.fuel_type,
        )
        .order_by(models.Dispenser.dispenser_number.asc(), models.Nozzle.nozzle_number.asc())
        .all()
    )
    
    return [
        {
            "dispenser_number": item.dispenser_number,
            "nozzle_number": item.nozzle_number,
            "product_name": item.product_name,
            "fuel_type": item.fuel_type,
            "transactions": item.transactions,
            "quantity": float(item.quantity),
            "revenue": float(item.revenue)
        }
        for item in dispenser_sales
    ]
