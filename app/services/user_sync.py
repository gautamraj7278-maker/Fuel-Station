from sqlalchemy.orm import Session

from app.supabase_auth import get_user_from_supabase
from app.models import User, Employee


def sync_user(db: Session, token: str):
    """
    Sync Supabase user + ensure employee record exists
    """

    supabase_user = get_user_from_supabase(token)

    if not supabase_user:
        return None

    user_id = supabase_user.get("user_id")
    email = supabase_user.get("email")
    role = supabase_user.get("role", "user")

    if not user_id:
        return None

    # -----------------------------
    # USER SYNC
    # -----------------------------
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        user = User(
            id=user_id,
            email=email,
            role=role
        )
        db.add(user)
    else:
        # keep DB in sync with Supabase
        user.email = email
        user.role = role

    # -----------------------------
    # EMPLOYEE SYNC
    # -----------------------------
    employee = db.query(Employee).filter(Employee.user_id == user_id).first()

    if not employee:
        # Create default employee record linked to the user
        employee = Employee(
            user_id=user_id,
            employee_name=email.split("@")[0],
            is_active=True
        )
        db.add(employee)

    db.commit()
    db.refresh(user)
    db.refresh(employee)

    return {
        "user": user,
        "employee": employee
    }