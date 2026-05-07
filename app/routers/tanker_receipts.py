from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional
import json

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.deletion_requests import queue_deletion_request
from app.routers.auth import require_admin, require_manager_or_admin, require_ops_access

router = APIRouter()


@router.get("/deleted", response_model=List[schemas.DeletedTankerReceipt])
def list_deleted_receipts(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    return (
        db.query(models.DeletedTankerReceipt)
        .order_by(models.DeletedTankerReceipt.deleted_at.desc(), models.DeletedTankerReceipt.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.delete("/deleted/{deleted_id}", status_code=status.HTTP_204_NO_CONTENT)
def purge_deleted_receipt(
    deleted_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    row = db.query(models.DeletedTankerReceipt).filter(models.DeletedTankerReceipt.id == deleted_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Deleted tanker receipt record not found")
    db.delete(row)
    db.commit()
    return None


@router.post("/deleted/{deleted_id}/restore", response_model=schemas.TankerReceipt)
def restore_deleted_receipt(
    deleted_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    row = db.query(models.DeletedTankerReceipt).filter(models.DeletedTankerReceipt.id == deleted_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Deleted receipt record not found")

    payload = {
        "receipt_date": row.receipt_date,
        "tanker_no": row.tanker_no,
        "transporter_name": row.transporter_name,
        "driver_name": row.driver_name,
        "invoice_no": row.invoice_no,
        "product_id": row.product_id,
        "dips_invoice_mm": row.dips_invoice_mm,
        "dips_site_mm": row.dips_site_mm,
        "quantity_invoice_litres": row.quantity_invoice_litres,
        "density_invoice": row.density_invoice,
        "density_site": row.density_site,
        "temperature_c": row.temperature_c,
        "remarks": row.remarks,
        "status": row.status,
        "confirmed_at": row.confirmed_at,
        "confirmed_by_user_id": row.confirmed_by_user_id,
        "created_by_user_id": row.created_by_user_id,
        "created_at": row.created_at or datetime.utcnow(),
    }
    receipt = models.TankerReceipt(**payload)
    db.add(receipt)
    db.flush()

    compartments = []
    if row.compartments_json:
        try:
            compartments = json.loads(row.compartments_json) or []
        except Exception:
            compartments = []
    for comp in compartments:
        db.add(
            models.TankerReceiptCompartment(
                receipt_id=receipt.id,
                product_id=comp.get("product_id"),
                dips_invoice_mm=comp.get("dips_invoice_mm"),
                dips_site_mm=comp.get("dips_site_mm"),
                quantity_invoice_litres=comp.get("quantity_invoice_litres"),
                density_invoice=comp.get("density_invoice"),
                density_site=comp.get("density_site"),
                temperature_c=comp.get("temperature_c"),
                remarks=comp.get("remarks"),
            )
        )

    lines = []
    if row.lines_json:
        try:
            lines = json.loads(row.lines_json) or []
        except Exception:
            lines = []
    for line in lines:
        db.add(
            models.TankerReceiptLine(
                receipt_id=receipt.id,
                compartment_id=None,
                tank_id=line.get("tank_id"),
                product_id=line.get("product_id"),
                before_dips_mm=line.get("before_dips_mm"),
                after_dips_mm=line.get("after_dips_mm"),
                before_volume_litres=line.get("before_volume_litres"),
                after_volume_litres=line.get("after_volume_litres"),
                received_volume_litres=line.get("received_volume_litres"),
                remarks=line.get("remarks"),
            )
        )

    db.delete(row)
    db.commit()
    db.refresh(receipt)
    return receipt


def _interpolate_volume(points: List[models.TankCalibrationPoint], dips_mm: float) -> float:
    if dips_mm < 0:
        raise HTTPException(status_code=400, detail="Dips must be >= 0")

    pts = sorted(points, key=lambda p: float(p.dips_mm))
    if not pts:
        raise HTTPException(status_code=400, detail="No calibration points found for tank")

    if dips_mm < float(pts[0].dips_mm) or dips_mm > float(pts[-1].dips_mm):
        raise HTTPException(
            status_code=400,
            detail=f"Dip {dips_mm}mm is outside calibration range ({pts[0].dips_mm}mm - {pts[-1].dips_mm}mm)",
        )

    # exact hit
    for p in pts:
        if float(p.dips_mm) == float(dips_mm):
            return float(p.volume_in_litres)

    # find bounding points
    lower = None
    upper = None
    for p in pts:
        if float(p.dips_mm) < dips_mm:
            lower = p
        elif float(p.dips_mm) > dips_mm:
            upper = p
            break

    if lower is None or upper is None:
        raise HTTPException(status_code=400, detail="Unable to interpolate dip")

    x0 = float(lower.dips_mm)
    y0 = float(lower.volume_in_litres)
    x1 = float(upper.dips_mm)
    y1 = float(upper.volume_in_litres)

    if x1 == x0:
        return float(y0)

    ratio = (dips_mm - x0) / (x1 - x0)
    return float(y0 + ratio * (y1 - y0))


def _compute_line(db: Session, *, tank: models.Tank, before_dips_mm: float, after_dips_mm: float):
    points = (
        db.query(models.TankCalibrationPoint)
        .filter(models.TankCalibrationPoint.tank_id == tank.id)
        .order_by(models.TankCalibrationPoint.dips_mm.asc())
        .all()
    )
    if not points:
        raise HTTPException(
            status_code=400,
            detail=f"No calibration points found for tank '{tank.tank_name}' (id={tank.id})",
        )

    try:
        before_volume = _interpolate_volume(points, before_dips_mm)
        after_volume = _interpolate_volume(points, after_dips_mm)
    except HTTPException as e:
        # Add tank context to calibration-related errors.
        if int(getattr(e, "status_code", 0) or 0) == 400:
            raise HTTPException(status_code=400, detail=f"Tank '{tank.tank_name}' (id={tank.id}): {e.detail}")
        raise

    received = after_volume - before_volume
    if received < 0:
        raise HTTPException(
            status_code=400,
            detail=f"Tank '{tank.tank_name}' (id={tank.id}): After dip volume is less than before dip volume",
        )
    return before_volume, after_volume, received


def _maybe_compute_line(db: Session, *, tank: models.Tank, before_dips_mm: float, after_dips_mm: float):
    """Compute volumes if calibration data supports it.

    Draft receipts can be saved even without calibration; volumes will be NULL.
    """

    try:
        return _compute_line(db, tank=tank, before_dips_mm=before_dips_mm, after_dips_mm=after_dips_mm)
    except HTTPException as e:
        if int(getattr(e, "status_code", 0) or 0) == 400:
            return None, None, None
        raise


@router.get("/", response_model=List[schemas.TankerReceipt])
def list_receipts(
    receipt_date_from: Optional[date] = None,
    receipt_date_to: Optional[date] = None,
    status_filter: Optional[schemas.TankerReceiptStatus] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access),
):
    q = db.query(models.TankerReceipt)
    if receipt_date_from is not None:
        q = q.filter(models.TankerReceipt.receipt_date >= receipt_date_from)
    if receipt_date_to is not None:
        q = q.filter(models.TankerReceipt.receipt_date <= receipt_date_to)
    if status_filter is not None:
        q = q.filter(models.TankerReceipt.status == models.TankerReceiptStatus(status_filter.value))
    return q.order_by(models.TankerReceipt.receipt_date.desc(), models.TankerReceipt.id.desc()).all()


@router.get("/{receipt_id}", response_model=schemas.TankerReceipt)
def get_receipt(
    receipt_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access),
):
    receipt = db.query(models.TankerReceipt).filter(models.TankerReceipt.id == receipt_id).first()
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return receipt


@router.post("/", response_model=schemas.TankerReceipt, status_code=status.HTTP_201_CREATED)
def create_receipt(
    payload: schemas.TankerReceiptCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access),
):
    if not payload.lines:
        raise HTTPException(status_code=400, detail="At least one tank line is required")

    receipt = models.TankerReceipt(
        receipt_date=payload.receipt_date,
        tanker_no=payload.tanker_no,
        transporter_name=payload.transporter_name,
        driver_name=payload.driver_name,
        invoice_no=payload.invoice_no,
        # legacy single-compartment fields (optional)
        product_id=payload.product_id,
        dips_invoice_mm=payload.dips_invoice_mm,
        dips_site_mm=payload.dips_site_mm,
        quantity_invoice_litres=payload.quantity_invoice_litres,
        density_invoice=payload.density_invoice,
        density_site=payload.density_site,
        temperature_c=payload.temperature_c,
        remarks=payload.remarks,
        status=models.TankerReceiptStatus.DRAFT,
        created_by_user_id=current_user.id,
    )

    db.add(receipt)
    db.flush()  # allocate id

    # Build compartments (multi-product support)
    compartments_payload = list(payload.compartments or [])
    if not compartments_payload and payload.product_id is not None:
        # Backward-compat: create a single compartment from legacy fields.
        compartments_payload = [
            schemas.TankerReceiptCompartmentCreate(
                product_id=payload.product_id,
                dips_invoice_mm=payload.dips_invoice_mm,
                dips_site_mm=payload.dips_site_mm,
                quantity_invoice_litres=payload.quantity_invoice_litres,
                density_invoice=payload.density_invoice,
                density_site=payload.density_site,
                temperature_c=payload.temperature_c,
                remarks=None,
            )
        ]

    # If multiple products are present in tank lines, compartments must be provided.
    line_product_ids = set()
    for line in payload.lines:
        tank = db.query(models.Tank).filter(models.Tank.id == line.tank_id).first()
        if tank:
            line_product_ids.add(int(tank.product_id))

    # Note: compartments are optional for saving drafts; they mainly capture per-product invoice metadata.

    compartments_by_product: dict[int, list[models.TankerReceiptCompartment]] = {}
    for comp in compartments_payload:
        db_comp = models.TankerReceiptCompartment(
            receipt_id=receipt.id,
            product_id=int(comp.product_id),
            dips_invoice_mm=comp.dips_invoice_mm,
            dips_site_mm=comp.dips_site_mm,
            quantity_invoice_litres=comp.quantity_invoice_litres,
            density_invoice=comp.density_invoice,
            density_site=comp.density_site,
            temperature_c=comp.temperature_c,
            remarks=comp.remarks,
        )
        db.add(db_comp)
        db.flush()
        compartments_by_product.setdefault(int(comp.product_id), []).append(db_comp)

    for line in payload.lines:
        tank = db.query(models.Tank).filter(models.Tank.id == line.tank_id).first()
        if not tank:
            raise HTTPException(status_code=404, detail=f"Tank not found: {line.tank_id}")

        comp_list = compartments_by_product.get(int(tank.product_id)) if compartments_by_product else None
        comp = (comp_list[0] if comp_list else None)
        if compartments_payload and comp is None:
            raise HTTPException(status_code=400, detail="Tank product does not match any receipt compartment")

        before_volume, after_volume, received = _maybe_compute_line(
            db,
            tank=tank,
            before_dips_mm=float(line.before_dips_mm),
            after_dips_mm=float(line.after_dips_mm),
        )

        db.add(
            models.TankerReceiptLine(
                receipt_id=receipt.id,
                compartment_id=(comp.id if comp is not None else None),
                tank_id=tank.id,
                product_id=tank.product_id,
                before_dips_mm=float(line.before_dips_mm),
                after_dips_mm=float(line.after_dips_mm),
                before_volume_litres=before_volume,
                after_volume_litres=after_volume,
                received_volume_litres=received,
                remarks=line.remarks,
            )
        )

    db.commit()
    db.refresh(receipt)
    return receipt


@router.put("/{receipt_id}", response_model=schemas.TankerReceipt)
def update_receipt(
    receipt_id: int,
    payload: schemas.TankerReceiptUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access),
):
    receipt = db.query(models.TankerReceipt).filter(models.TankerReceipt.id == receipt_id).first()
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    if receipt.status != models.TankerReceiptStatus.DRAFT and current_user.role != models.UserRole.ADMIN:
        raise HTTPException(status_code=400, detail="Only admins can edit confirmed receipts")

    # Keep nested objects as Pydantic models (model_dump turns them into dicts).
    compartments = payload.compartments
    lines = payload.lines
    data = payload.model_dump(exclude_unset=True, exclude={"compartments", "lines"})

    was_confirmed = receipt.status == models.TankerReceiptStatus.CONFIRMED
    old_received_by_tank: dict[int, float] = {}
    old_received_by_fuel: dict[str, float] = {}
    if was_confirmed:
        for line in receipt.lines or []:
            tank = db.query(models.Tank).filter(models.Tank.id == line.tank_id).first()
            if not tank:
                raise HTTPException(status_code=404, detail=f"Tank not found: {line.tank_id}")
            product = db.query(models.Product).filter(models.Product.id == tank.product_id).first()
            if not product:
                raise HTTPException(status_code=400, detail="Tank product is missing")
            received = float(line.received_volume_litres or 0.0)
            old_received_by_tank[int(tank.id)] = float(old_received_by_tank.get(int(tank.id), 0.0) + received)
            old_received_by_fuel[product.fuel_type] = float(old_received_by_fuel.get(product.fuel_type, 0.0) + received)

    for k, v in data.items():
        setattr(receipt, k, v)

    if compartments is not None:
        receipt.compartments.clear()
        db.flush()
        for comp in compartments:
            receipt.compartments.append(
                models.TankerReceiptCompartment(
                    product_id=int(comp.product_id),
                    dips_invoice_mm=comp.dips_invoice_mm,
                    dips_site_mm=comp.dips_site_mm,
                    quantity_invoice_litres=comp.quantity_invoice_litres,
                    density_invoice=comp.density_invoice,
                    density_site=comp.density_site,
                    temperature_c=comp.temperature_c,
                    remarks=comp.remarks,
                )
            )
        db.flush()

    compartments_by_product: dict[int, list[models.TankerReceiptCompartment]] = {}
    for comp in (receipt.compartments or []):
        compartments_by_product.setdefault(int(comp.product_id), []).append(comp)

    new_received_by_tank: dict[int, float] = {}
    new_received_by_fuel: dict[str, float] = {}
    if lines is not None:
        # Replace all lines
        receipt.lines.clear()
        db.flush()
        for line in lines:
            tank = db.query(models.Tank).filter(models.Tank.id == line.tank_id).first()
            if not tank:
                raise HTTPException(status_code=404, detail=f"Tank not found: {line.tank_id}")

            comp_list = compartments_by_product.get(int(tank.product_id)) if compartments_by_product else None
            comp = (comp_list[0] if comp_list else None)
            if receipt.compartments and comp is None:
                raise HTTPException(status_code=400, detail="Tank product does not match any receipt compartment")

            if was_confirmed:
                if bool(getattr(tank, "is_buffer", False)):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot offload tanker receipts into buffer tank '{tank.tank_name}'. Select a main tank.",
                    )
                before_volume, after_volume, received = _compute_line(
                    db,
                    tank=tank,
                    before_dips_mm=float(line.before_dips_mm),
                    after_dips_mm=float(line.after_dips_mm),
                )
            else:
                before_volume, after_volume, received = _maybe_compute_line(
                    db,
                    tank=tank,
                    before_dips_mm=float(line.before_dips_mm),
                    after_dips_mm=float(line.after_dips_mm),
                )

            receipt.lines.append(
                models.TankerReceiptLine(
                    compartment_id=(comp.id if comp is not None else None),
                    tank_id=tank.id,
                    product_id=tank.product_id,
                    before_dips_mm=float(line.before_dips_mm),
                    after_dips_mm=float(line.after_dips_mm),
                    before_volume_litres=before_volume,
                    after_volume_litres=after_volume,
                    received_volume_litres=received,
                    remarks=line.remarks,
                )
            )
            if was_confirmed:
                received_val = float(received or 0.0)
                new_received_by_tank[int(tank.id)] = float(new_received_by_tank.get(int(tank.id), 0.0) + received_val)
                product = db.query(models.Product).filter(models.Product.id == tank.product_id).first()
                if not product:
                    raise HTTPException(status_code=400, detail="Tank product is missing")
                new_received_by_fuel[product.fuel_type] = float(new_received_by_fuel.get(product.fuel_type, 0.0) + received_val)

    if was_confirmed:
        # Apply delta adjustments to tanks and inventory.
        for tank_id, old_received in old_received_by_tank.items():
            new_received = float(new_received_by_tank.get(int(tank_id), 0.0))
            delta = float(new_received - old_received)
            if delta == 0:
                continue
            tank = db.query(models.Tank).filter(models.Tank.id == int(tank_id)).first()
            if not tank:
                raise HTTPException(status_code=404, detail=f"Tank not found: {tank_id}")
            prev = float(tank.current_volume or 0.0)
            next_vol = prev + delta
            if next_vol < 0:
                raise HTTPException(status_code=400, detail=f"Tank '{tank.tank_name}' volume would become negative")
            tank.current_volume = next_vol
            db.add(
                models.TankStockLog(
                    tank_id=tank.id,
                    action="tanker_edit",
                    quantity=delta,
                    previous_volume=prev,
                    new_volume=float(tank.current_volume),
                    notes=f"Tanker receipt {receipt.id} edited",
                    related_receipt_id=receipt.id,
                    created_by_user_id=current_user.id,
                )
            )

        for fuel_type, old_received in old_received_by_fuel.items():
            new_received = float(new_received_by_fuel.get(fuel_type, 0.0))
            delta = float(new_received - old_received)
            if delta == 0:
                continue
            inv = db.query(models.FuelInventory).filter(models.FuelInventory.fuel_type == fuel_type).first()
            if inv is None:
                inv = models.FuelInventory(
                    fuel_type=fuel_type,
                    current_stock=0.0,
                    price_per_liter=0.01,
                    reorder_level=0.0,
                )
                db.add(inv)
                db.flush()
            previous_stock = float(inv.current_stock or 0.0)
            inv.current_stock = previous_stock + delta
            db.add(
                models.InventoryLog(
                    fuel_type=fuel_type,
                    action="tanker_receipt_edit",
                    quantity=float(delta),
                    previous_stock=previous_stock,
                    new_stock=float(inv.current_stock),
                    notes=f"Tanker receipt {receipt.id} edited",
                )
            )

        receipt.confirmed_at = datetime.utcnow()
        receipt.confirmed_by_user_id = current_user.id

    db.commit()
    db.refresh(receipt)
    return receipt


@router.post("/{receipt_id}/confirm", response_model=schemas.TankerReceipt)
def confirm_receipt(
    receipt_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_ops_access),
):
    receipt = db.query(models.TankerReceipt).filter(models.TankerReceipt.id == receipt_id).first()
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    if receipt.status != models.TankerReceiptStatus.DRAFT:
        raise HTTPException(status_code=400, detail="Only draft receipts can be confirmed")
    if not receipt.lines:
        raise HTTPException(status_code=400, detail="Receipt has no tank lines")

    # Recompute and apply stock updates (confirmation is the source of truth)
    deltas_by_fuel_type: dict[str, float] = {}
    for line in receipt.lines:
        tank = db.query(models.Tank).filter(models.Tank.id == line.tank_id).first()
        if not tank:
            raise HTTPException(status_code=404, detail=f"Tank not found: {line.tank_id}")

        if bool(getattr(tank, "is_buffer", False)):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot offload tanker receipts into buffer tank '{tank.tank_name}'. Select a main tank.",
            )

        product = db.query(models.Product).filter(models.Product.id == tank.product_id).first()
        if not product:
            raise HTTPException(status_code=400, detail="Tank product is missing")

        # Ensure volumes exist and are computed from current calibration.
        before_volume, after_volume, received = _compute_line(
            db,
            tank=tank,
            before_dips_mm=float(line.before_dips_mm),
            after_dips_mm=float(line.after_dips_mm),
        )
        line.before_volume_litres = before_volume
        line.after_volume_litres = after_volume
        line.received_volume_litres = received

        delta = float(received)
        prev = float(tank.current_volume or 0)
        tank.current_volume = prev + delta

        deltas_by_fuel_type[product.fuel_type] = float(deltas_by_fuel_type.get(product.fuel_type, 0.0) + delta)

        db.add(
            models.TankStockLog(
                tank_id=tank.id,
                action="tanker_confirm",
                quantity=delta,
                previous_volume=prev,
                new_volume=float(tank.current_volume),
                notes=f"Tanker receipt {receipt.id} confirmed",
                related_receipt_id=receipt.id,
                created_by_user_id=current_user.id,
            )
        )

    # Update FuelInventory (manual restock is disabled; tanker confirmation is the source of truth)
    for fuel_type, delta in deltas_by_fuel_type.items():
        inv = db.query(models.FuelInventory).filter(models.FuelInventory.fuel_type == fuel_type).first()
        if inv is None:
            # Keep system functional even if inventory wasn't initialized yet.
            inv = models.FuelInventory(
                fuel_type=fuel_type,
                current_stock=0.0,
                price_per_liter=0.01,
                reorder_level=0.0,
            )
            db.add(inv)
            db.flush()

        previous_stock = float(inv.current_stock or 0.0)
        inv.current_stock = previous_stock + float(delta)

        db.add(
            models.InventoryLog(
                fuel_type=fuel_type,
                action="tanker_receipt",
                quantity=float(delta),
                previous_stock=previous_stock,
                new_stock=float(inv.current_stock),
                notes=f"Tanker receipt {receipt.id} confirmed",
            )
        )

    receipt.status = models.TankerReceiptStatus.CONFIRMED
    receipt.confirmed_at = datetime.utcnow()
    receipt.confirmed_by_user_id = current_user.id

    db.commit()
    db.refresh(receipt)
    return receipt


def _snapshot_receipt(receipt: models.TankerReceipt) -> tuple[str, str]:
    compartments = [
        {
            "id": c.id,
            "product_id": c.product_id,
            "dips_invoice_mm": c.dips_invoice_mm,
            "dips_site_mm": c.dips_site_mm,
            "quantity_invoice_litres": c.quantity_invoice_litres,
            "density_invoice": c.density_invoice,
            "density_site": c.density_site,
            "temperature_c": c.temperature_c,
            "remarks": c.remarks,
            "created_at": (c.created_at.isoformat() if getattr(c, "created_at", None) else None),
        }
        for c in (receipt.compartments or [])
    ]
    lines = [
        {
            "id": l.id,
            "tank_id": l.tank_id,
            "product_id": l.product_id,
            "before_dips_mm": l.before_dips_mm,
            "after_dips_mm": l.after_dips_mm,
            "before_volume_litres": l.before_volume_litres,
            "after_volume_litres": l.after_volume_litres,
            "received_volume_litres": l.received_volume_litres,
            "remarks": l.remarks,
            "created_at": (l.created_at.isoformat() if getattr(l, "created_at", None) else None),
        }
        for l in (receipt.lines or [])
    ]
    return json.dumps(compartments, default=str), json.dumps(lines, default=str)


@router.delete("/{receipt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_receipt(
    receipt_id: int,
    reason: Optional[str] = Query(None, max_length=200),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_manager_or_admin),
):
    """Soft-delete a tanker receipt.

    - Draft receipts: can be deleted directly.
    - Confirmed receipts: deletion reverses tank volumes and fuel inventory stock first.
    """

    receipt = db.query(models.TankerReceipt).filter(models.TankerReceipt.id == receipt_id).first()
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    if current_user.role == models.UserRole.MANAGER:
        request = queue_deletion_request(
            db=db,
            target_type=models.DeletionTargetType.TANKER_RECEIPT,
            target_id=receipt.id,
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

    perform_receipt_delete(receipt=receipt, reason=reason, db=db, current_user=current_user)
    db.commit()
    return None


def perform_receipt_delete(
    *,
    receipt: models.TankerReceipt,
    reason: Optional[str],
    db: Session,
    current_user: models.User,
) -> models.DeletedTankerReceipt:
    # Reverse stock if confirmed
    if receipt.status == models.TankerReceiptStatus.CONFIRMED:
        deltas_by_fuel_type: dict[str, float] = {}
        for line in (receipt.lines or []):
            tank = db.query(models.Tank).filter(models.Tank.id == line.tank_id).first()
            if not tank:
                raise HTTPException(status_code=404, detail=f"Tank not found: {line.tank_id}")

            product = db.query(models.Product).filter(models.Product.id == tank.product_id).first()
            if not product:
                raise HTTPException(status_code=400, detail="Tank product is missing")

            delta = float(line.received_volume_litres or 0.0)
            prev = float(tank.current_volume or 0.0)
            next_vol = prev - delta
            if next_vol < 0:
                raise HTTPException(status_code=400, detail=f"Cannot delete: tank '{tank.tank_name}' volume would become negative")
            tank.current_volume = next_vol

            deltas_by_fuel_type[product.fuel_type] = float(deltas_by_fuel_type.get(product.fuel_type, 0.0) + delta)

            db.add(
                models.TankStockLog(
                    tank_id=tank.id,
                    action="tanker_delete",
                    quantity=-delta,
                    previous_volume=prev,
                    new_volume=float(tank.current_volume),
                    notes=f"Tanker receipt {receipt.id} deleted (reversal)",
                    related_receipt_id=receipt.id,
                    created_by_user_id=current_user.id,
                )
            )

        for fuel_type, delta in deltas_by_fuel_type.items():
            inv = db.query(models.FuelInventory).filter(models.FuelInventory.fuel_type == fuel_type).first()
            if inv is not None:
                previous_stock = float(inv.current_stock or 0.0)
                next_stock = previous_stock - float(delta)
                if next_stock < 0:
                    raise HTTPException(status_code=400, detail=f"Cannot delete: inventory stock for {fuel_type} would become negative")
                inv.current_stock = next_stock
                db.add(
                    models.InventoryLog(
                        fuel_type=fuel_type,
                        action="tanker_receipt_delete",
                        quantity=-float(delta),
                        previous_stock=previous_stock,
                        new_stock=float(inv.current_stock),
                        notes=f"Deleted tanker receipt {receipt.id}",
                    )
                )

    compartments_json, lines_json = _snapshot_receipt(receipt)
    delete_reason = reason.strip() if isinstance(reason, str) and reason.strip() else None
    deleted = models.DeletedTankerReceipt(
        original_receipt_id=receipt.id,
        receipt_date=receipt.receipt_date,
        tanker_no=receipt.tanker_no,
        transporter_name=receipt.transporter_name,
        driver_name=receipt.driver_name,
        invoice_no=receipt.invoice_no,
        remarks=receipt.remarks,
        status=receipt.status,
        confirmed_at=receipt.confirmed_at,
        confirmed_by_user_id=receipt.confirmed_by_user_id,
        created_by_user_id=receipt.created_by_user_id,
        created_at=receipt.created_at,
        compartments_json=compartments_json,
        lines_json=lines_json,
        deleted_at=datetime.utcnow(),
        deleted_by_user_id=current_user.id,
        delete_reason=delete_reason,
    )
    db.add(deleted)
    db.delete(receipt)
    return deleted


