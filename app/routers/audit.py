from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.routers.auth import require_admin

router = APIRouter()


@router.get("/", response_model=List[schemas.AuditLog])
def list_audit_logs(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    method: Optional[str] = None,
    path_contains: Optional[str] = None,
    success: Optional[bool] = None,
    status_min: Optional[int] = Query(None, ge=100, le=599),
    status_max: Optional[int] = Query(None, ge=100, le=599),
):
    q = db.query(models.AuditLog)

    if from_dt is not None:
        q = q.filter(models.AuditLog.created_at >= from_dt)
    if to_dt is not None:
        q = q.filter(models.AuditLog.created_at <= to_dt)
    if user_id is not None:
        q = q.filter(models.AuditLog.user_id == user_id)
    if username:
        q = q.filter(models.AuditLog.username.ilike(f"%{username}%"))
    if method:
        q = q.filter(models.AuditLog.method == method.upper())
    if path_contains:
        q = q.filter(models.AuditLog.path.ilike(f"%{path_contains}%"))
    if success is not None:
        q = q.filter(models.AuditLog.success == success)
    if status_min is not None:
        q = q.filter(models.AuditLog.status_code >= status_min)
    if status_max is not None:
        q = q.filter(models.AuditLog.status_code <= status_max)

    return (
        q.order_by(models.AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
