from fastapi import APIRouter, Depends

from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role

router = APIRouter(prefix="/auth", tags=["Auth"])

# -------------------------------------------------
# RBAC DEPENDENCIES (EXPORTED FOR OTHER ROUTERS)
# -------------------------------------------------
require_admin = require_role("admin")
require_manager = require_role(["admin", "manager"])
require_manager_or_admin = require_role(["admin", "manager"])
require_operator = require_role(["admin", "manager", "operator"])
require_cashier = require_role(["admin", "manager", "cashier", "operator"])
require_ops_access = require_role(["admin", "manager", "operator", "cashier"])


# -------------------------------------------------
# GET CURRENT USER PROFILE
# -------------------------------------------------
@router.get("/me")
def get_me(user=Depends(get_current_user)):
    """
    Returns current authenticated user
    """
    return {
        "status": "success",
        "user": user
    }


# -------------------------------------------------
# TOKEN VALIDATION ENDPOINT
# -------------------------------------------------
@router.get("/verify")
def verify_user(user=Depends(get_current_user)):
    """
    Simple endpoint to verify token validity
    """
    return {    
        "valid": True,
        "user_id": user.id,
        "email": user.email,
        "role": user.role
    }


# -------------------------------------------------
# ADMIN TEST ENDPOINT (RBAC CHECK)
# -------------------------------------------------
@router.get("/admin-check")
def admin_check(user=Depends(require_admin)):
    """
    Only admin can access this
    """
    return {
        "status": "success",
        "message": "You are an admin",
        "user": user
    }