from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app import models
from app.auth import get_password_hash
from pydantic import BaseModel, Field
from app.routers.auth import require_admin

router = APIRouter()

class SetupStatus(BaseModel):
    is_setup: bool
    has_admin: bool
    has_inventory: bool
    has_dispensers: bool
    message: str

class SetupRequest(BaseModel):
    admin_username: str = "admin"
    admin_password: str = Field(min_length=6, max_length=72, description="Password (6-72 characters)")
    admin_email: str = "admin@fuelstation.com"
    admin_full_name: str = "System Administrator"

@router.get("/status", response_model=SetupStatus)
def check_setup_status(db: Session = Depends(get_db)):
    """Check if initial setup is complete"""
    
    # Check for admin users
    admin_count = db.query(models.User).filter(
        models.User.role == models.UserRole.ADMIN
    ).count()
    
    # Check for inventory
    inventory_count = db.query(models.FuelInventory).count()
    
    # Check for dispensers
    dispenser_count = db.query(models.Dispenser).count()
    
    # Dispensers and inventory are user-configured in the UI.
    is_setup = admin_count > 0
    
    return {
        "is_setup": is_setup,
        "has_admin": admin_count > 0,
        "has_inventory": inventory_count > 0,
        "has_dispensers": dispenser_count > 0,
        "message": "System is ready" if is_setup else "Setup required"
    }

@router.post("/initialize", response_model=dict)
def initialize_system(setup: SetupRequest, db: Session = Depends(get_db)):
    """One-click system initialization (creates admin and inventory)."""
    
    results = {
        "success": True,
        "created": [],
        "errors": []
    }
    
    try:
        # 1. Create Admin User
        # bcrypt only uses first 72 bytes; passlib may raise if longer.
        # Validate bytes here to return a user-friendly error.
        password_bytes_len = len(setup.admin_password.encode("utf-8"))
        if password_bytes_len > 72:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Admin password is too long ({password_bytes_len} bytes). "
                    "bcrypt supports max 72 bytes. Use a shorter password or ASCII characters."
                ),
            )

        existing_admin = db.query(models.User).filter(
            models.User.username == setup.admin_username
        ).first()
        
        if not existing_admin:
            admin_user = models.User(
                username=setup.admin_username,
                email=setup.admin_email,
                hashed_password=get_password_hash(setup.admin_password),
                full_name=setup.admin_full_name,
                role=models.UserRole.ADMIN,
                is_active=True
            )
            db.add(admin_user)
            results["created"].append(f"Admin user: {setup.admin_username}")
        else:
            results["errors"].append("Admin user already exists")
        
        db.commit()
        
        results["message"] = "System initialized successfully!"
        results["credentials"] = {
            "username": setup.admin_username,
            "password": "*** (as provided)",
            "note": "Please save these credentials securely"
        }
        
    except Exception as e:
        db.rollback()
        results["success"] = False
        results["errors"].append(str(e))
        results["message"] = "Initialization failed"
    
    return results


@router.post("/cleanup-default-dispensers", response_model=dict)
def cleanup_default_dispensers(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """Delete dispensers that are safe to remove (no sales / shift assignments).

    Intended to help remove old seeded dispensers from earlier versions.
    """

    dispensers = db.query(models.Dispenser).all()
    deleted: list[dict] = []
    skipped: list[dict] = []

    for d in dispensers:
        has_sales = db.query(models.Sale).filter(models.Sale.dispenser_id == d.id).first() is not None
        has_assignments = (
            db.query(models.DispenserShiftAssignment)
            .filter(models.DispenserShiftAssignment.dispenser_id == d.id)
            .first()
            is not None
        )

        if has_sales or has_assignments:
            skipped.append(
                {
                    "id": d.id,
                    "dispenser_number": d.dispenser_number,
                    "reason": "has sales" if has_sales else "has shift assignments",
                }
            )
            continue

        db.delete(d)
        deleted.append({"id": d.id, "dispenser_number": d.dispenser_number})

    db.commit()
    return {
        "success": True,
        "deleted_count": len(deleted),
        "skipped_count": len(skipped),
        "deleted": deleted,
        "skipped": skipped,
        "message": "Cleanup complete",
    }
