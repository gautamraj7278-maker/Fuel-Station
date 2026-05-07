from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app import models, schemas
from app.auth import get_password_hash
from app.database import get_db
from app.routers.auth import require_admin

router = APIRouter()


def _coerce_role(role_value) -> models.UserRole:
    if isinstance(role_value, models.UserRole):
        role = role_value
    else:
        raw = role_value.value if hasattr(role_value, "value") else role_value
        raw_text = str(raw).strip()
        if "." in raw_text:
            raw_text = raw_text.split(".")[-1]
        raw_text = raw_text.lower()
        role = models.UserRole(raw_text)
    if role == models.UserRole.CASHIER:
        return models.UserRole.OPERATOR
    return role


def _ensure_admin_guard(db: Session, *, target_user: models.User, acting_user: models.User) -> None:
    if target_user.id == acting_user.id:
        raise HTTPException(status_code=400, detail="You cannot modify your own role or status here")

    if target_user.role != models.UserRole.ADMIN:
        return

    admin_count = db.query(models.User).filter(models.User.role == models.UserRole.ADMIN, models.User.is_active == True).count()  # noqa: E712
    if admin_count <= 1:
        raise HTTPException(status_code=400, detail="Cannot modify the last active admin account")


@router.get("/", response_model=List[schemas.User])
def list_users(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    return db.query(models.User).order_by(models.User.created_at.desc(), models.User.id.desc()).all()


@router.post("/", response_model=schemas.User, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: schemas.UserAdminCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    if db.query(models.User).filter(models.User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already registered")
    if db.query(models.User).filter(models.User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    role = _coerce_role(payload.role)
    user = models.User(
        username=payload.username,
        email=payload.email,
        hashed_password=get_password_hash(payload.password),
        full_name=payload.full_name,
        role=role,
        is_active=bool(payload.is_active),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.put("/{user_id}", response_model=schemas.User)
def update_user(
    user_id: str,
    payload: schemas.UserAdminUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = payload.model_dump(exclude_unset=True)
    if "username" in update_data:
        exists = db.query(models.User).filter(models.User.username == update_data["username"], models.User.id != user.id).first()
        if exists:
            raise HTTPException(status_code=400, detail="Username already registered")
        user.username = update_data["username"]
    if "email" in update_data:
        exists = db.query(models.User).filter(models.User.email == update_data["email"], models.User.id != user.id).first()
        if exists:
            raise HTTPException(status_code=400, detail="Email already registered")
        user.email = update_data["email"]
    if "full_name" in update_data:
        user.full_name = update_data["full_name"]
    if "role" in update_data:
        _ensure_admin_guard(db, target_user=user, acting_user=current_user)
        # With Supabase, role might be a simple string
        user.role = update_data["role"]
    if "is_active" in update_data:
        if bool(update_data["is_active"]) is False:
            _ensure_admin_guard(db, target_user=user, acting_user=current_user)
        user.is_active = bool(update_data["is_active"])

    db.commit()
    db.refresh(user)
    return user


@router.put("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: str,
    payload: schemas.UserPasswordReset,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # Note: Password reset should ideally be handled via Supabase
    user.hashed_password = get_password_hash(payload.password)
    db.commit()
    return None


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    _ensure_admin_guard(db, target_user=user, acting_user=current_user)
    user.is_active = False
    db.commit()
    return None
