from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.deletion_requests import normalize_text
from app.routers.auth import require_admin
from app.routers.sales import perform_sale_delete
from app.routers.tanker_receipts import perform_receipt_delete

router = APIRouter()


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _build_target_info(db: Session, req: models.DeletionRequest) -> tuple[str, dict]:
    target_type = req.target_type
    label = f"{_enum_value(target_type)} #{req.target_id}"
    meta: dict = {}

    if target_type == models.DeletionTargetType.SALE:
        sale = db.query(models.Sale).filter(models.Sale.id == req.target_id).first()
        if sale:
            label = f"Sale {sale.transaction_id}"
            meta = {
                "transaction_id": sale.transaction_id,
                "business_date": sale.business_date.isoformat() if sale.business_date else None,
                "total_amount": float(sale.total_amount or 0.0),
                "quantity": float(sale.quantity or 0.0),
                "shift": _enum_value(sale.shift) if sale.shift else None,
                "transaction_type": _enum_value(sale.transaction_type) if sale.transaction_type else None,
            }
        else:
            meta = {"missing": True}
    elif target_type == models.DeletionTargetType.TANKER_RECEIPT:
        receipt = db.query(models.TankerReceipt).filter(models.TankerReceipt.id == req.target_id).first()
        if receipt:
            label = f"Receipt #{receipt.id}"
            meta = {
                "receipt_date": receipt.receipt_date.isoformat() if receipt.receipt_date else None,
                "tanker_no": receipt.tanker_no,
                "status": _enum_value(receipt.status) if receipt.status else None,
            }
        else:
            meta = {"missing": True}

    return label, meta


def _serialize_request(db: Session, req: models.DeletionRequest) -> dict:
    label, meta = _build_target_info(db, req)
    return {
        "id": req.id,
        "target_type": _enum_value(req.target_type),
        "target_id": req.target_id,
        "status": _enum_value(req.status),
        "reason": req.reason,
        "requested_by_user_id": req.requested_by_user_id,
        "requested_by_username": getattr(req.requested_by, "username", None),
        "requested_at": req.requested_at,
        "reviewed_by_user_id": req.reviewed_by_user_id,
        "reviewed_by_username": getattr(req.reviewed_by, "username", None),
        "reviewed_at": req.reviewed_at,
        "review_comment": req.review_comment,
        "target_label": label,
        "target_meta": meta,
    }


@router.get("/deletion-requests", response_model=List[schemas.DeletionRequest])
def list_deletion_requests(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
    status: Optional[schemas.DeletionRequestStatus] = Query(None),
):
    _ = current_user
    q = db.query(models.DeletionRequest)
    if status is not None:
        q = q.filter(models.DeletionRequest.status == models.DeletionRequestStatus(status.value))
    rows = (
        q.order_by(models.DeletionRequest.requested_at.desc(), models.DeletionRequest.id.desc())
        .all()
    )
    return [_serialize_request(db, r) for r in rows]


@router.post("/deletion-requests/{request_id}/approve", response_model=schemas.DeletionRequest)
def approve_deletion_request(
    request_id: int,
    payload: Optional[schemas.DeletionRequestReview] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    req = db.query(models.DeletionRequest).filter(models.DeletionRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Deletion request not found")
    if req.status != models.DeletionRequestStatus.PENDING:
        raise HTTPException(status_code=400, detail="Deletion request is already resolved")

    comment = normalize_text(payload.comment) if payload else None

    if req.target_type == models.DeletionTargetType.SALE:
        sale = db.query(models.Sale).filter(models.Sale.id == req.target_id).first()
        if not sale:
            req.status = models.DeletionRequestStatus.REJECTED
            req.reviewed_by_user_id = current_user.id
            req.reviewed_at = datetime.utcnow()
            req.review_comment = comment or "Target sale no longer exists"
            db.commit()
            return _serialize_request(db, req)
        perform_sale_delete(sale=sale, reason=req.reason, db=db, current_user=current_user)
    elif req.target_type == models.DeletionTargetType.TANKER_RECEIPT:
        receipt = db.query(models.TankerReceipt).filter(models.TankerReceipt.id == req.target_id).first()
        if not receipt:
            req.status = models.DeletionRequestStatus.REJECTED
            req.reviewed_by_user_id = current_user.id
            req.reviewed_at = datetime.utcnow()
            req.review_comment = comment or "Target receipt no longer exists"
            db.commit()
            return _serialize_request(db, req)
        perform_receipt_delete(receipt=receipt, reason=req.reason, db=db, current_user=current_user)
    else:
        raise HTTPException(status_code=400, detail="Unsupported deletion request type")

    req.status = models.DeletionRequestStatus.APPROVED
    req.reviewed_by_user_id = current_user.id
    req.reviewed_at = datetime.utcnow()
    req.review_comment = comment
    db.commit()
    return _serialize_request(db, req)


@router.post("/deletion-requests/{request_id}/reject", response_model=schemas.DeletionRequest)
def reject_deletion_request(
    request_id: int,
    payload: Optional[schemas.DeletionRequestReview] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    req = db.query(models.DeletionRequest).filter(models.DeletionRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Deletion request not found")
    if req.status != models.DeletionRequestStatus.PENDING:
        raise HTTPException(status_code=400, detail="Deletion request is already resolved")

    req.status = models.DeletionRequestStatus.REJECTED
    req.reviewed_by_user_id = current_user.id
    req.reviewed_at = datetime.utcnow()
    req.review_comment = normalize_text(payload.comment) if payload else None
    db.commit()
    return _serialize_request(db, req)
