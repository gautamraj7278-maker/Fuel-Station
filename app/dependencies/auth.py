from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Callable

from app.database import get_db
from app import models
from app.services.user_sync import sync_user
from app.supabase_auth import get_user_from_supabase


# Reads: Authorization: Bearer <token>
security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> models.User:
    """
    Validate Supabase token and return the local database User.

    Important:
    - We do NOT run sync_user on every request.
    - Normal protected API calls only verify token and read local user.
    - sync_user is only called if the local user does not exist yet.
    - This reduces DB writes and helps avoid connection pool exhaustion.
    """

    token = credentials.credentials

    supabase_user = get_user_from_supabase(token)

    if not supabase_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = supabase_user.get("user_id")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Read local user from DB
    user = db.query(models.User).filter(models.User.id == user_id).first()

    # First-time fallback only
    if not user:
        sync_result = sync_user(db, token)

        if not sync_result or not sync_result.get("user"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to sync user with local database",
            )

        user = sync_result["user"]

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    return user


def require_roles(*allowed_roles: str) -> Callable:
    """
    Role guard for protected routes.

    Example:
        current_user = Depends(require_roles("admin", "manager"))
    """

    def role_checker(
        current_user: models.User = Depends(get_current_user),
    ) -> models.User:
        user_role = (current_user.role or "").lower()
        allowed = [role.lower() for role in allowed_roles]

        if user_role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )

        return current_user

    return role_checker