# rbac.py
from fastapi import Depends, HTTPException, status
from typing import List, Union

from app.dependencies.auth import get_current_user
from app import models


def require_role(required_roles: Union[str, List[str]]):
    """
    Role-based access control dependency factory
    """

    if isinstance(required_roles, str):
        required_roles = [required_roles]

    def role_checker(user: models.User = Depends(get_current_user)):
        # user is now a models.User object from the local DB
        user_role = getattr(user, "role", None)

        if not user_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Role not found for user"
            )

        # Handle potential Enum or String roles
        role_name = user_role.value if hasattr(user_role, "value") else str(user_role)

        if role_name not in required_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {required_roles}"
            )

        return user

    return role_checker