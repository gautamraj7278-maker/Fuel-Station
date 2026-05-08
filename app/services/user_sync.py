from sqlalchemy.orm import Session

from app.supabase_auth import get_user_from_supabase
from app.models import User, Employee


def sync_user(db: Session, token: str):
    """
    Sync Supabase user + ensure employee record exists.

    IMPORTANT:
    - Supabase role is usually "authenticated"
    - Do NOT overwrite local DB role for existing users
    - App roles like admin/manager/operator/cashier must stay in public.users.role
    """

    supabase_user = get_user_from_supabase(token)

    if not supabase_user:
        return None

    user_id = supabase_user.get("user_id")
    email = supabase_user.get("email")

    if not user_id or not email:
        return None

    # -----------------------------
    # USER SYNC
    # -----------------------------
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        # First-time login: create app user
        # Default role should be "operator" or "user"; admin can be assigned manually later.
        user = User(
            id=user_id,
            email=email,
            role="operator",
            is_active=True,
        )
        db.add(user)
        db.flush()
    else:
        # Keep email synced, but DO NOT overwrite role
        user.email = email

        if user.is_active is None:
            user.is_active = True

    # -----------------------------
    # EMPLOYEE SYNC
    # -----------------------------
    employee = db.query(Employee).filter(Employee.user_id == user_id).first()

    if not employee:
        employee = Employee(
            user_id=user_id,
            employee_name=email.split("@")[0],
            is_active=True,
        )
        db.add(employee)
        db.flush()

    db.commit()
    db.refresh(user)
    db.refresh(employee)

    return {
        "user": user,
        "employee": employee,
    }