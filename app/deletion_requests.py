from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models


def normalize_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def queue_deletion_request(
    *,
    db: Session,
    target_type: models.DeletionTargetType,
    target_id: int,
    requested_by: models.User,
    reason: Optional[str] = None,
) -> models.DeletionRequest:
    pending = (
        db.query(models.DeletionRequest)
        .filter(
            models.DeletionRequest.target_type == target_type,
            models.DeletionRequest.target_id == target_id,
            models.DeletionRequest.status == models.DeletionRequestStatus.PENDING,
        )
        .first()
    )
    if pending:
        raise HTTPException(status_code=400, detail="Deletion request is already pending for this record")

    request = models.DeletionRequest(
        target_type=target_type,
        target_id=target_id,
        status=models.DeletionRequestStatus.PENDING,
        reason=normalize_text(reason),
        requested_by_user_id=requested_by.id,
        requested_at=datetime.utcnow(),
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request
