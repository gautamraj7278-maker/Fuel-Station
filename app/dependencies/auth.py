from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional

from app.database import get_db
from app import models
from app.services.user_sync import sync_user
from app.supabase_auth import get_user_from_supabase

# This reads: Authorization: Bearer <token>
security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> models.User:
    """
    Extract and validate Supabase user from Bearer token, 
    and return the synced local database User object.
    """

    token = credentials.credentials
    
    # This helper verifies the token with Supabase
    supabase_user = get_user_from_supabase(token)

    if not supabase_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Sync with local DB to get a proper User object with relationships
    # We use the token to sync the user info (email, role, etc.)
    sync_result = sync_user(db, token)
    
    if not sync_result or not sync_result.get("user"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to sync user with local database"
        )

    return sync_result["user"]