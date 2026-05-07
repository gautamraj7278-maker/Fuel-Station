from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

# -------------------------------------------------
# PASSWORD HASHING
# -------------------------------------------------

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify plain password against hashed password
    """
    if not plain_password or not hashed_password:
        return False

    try:
        # bcrypt has 72-byte limit safety check
        if len(plain_password.encode("utf-8")) > 72:
            return False

        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """
    Hash password using bcrypt
    """
    if len(password.encode("utf-8")) > 72:
        raise ValueError("Password too long for bcrypt (max 72 bytes)")

    return pwd_context.hash(password)


# -------------------------------------------------
# JWT TOKEN HANDLING
# -------------------------------------------------

ALGORITHM = settings.algorithm or "HS256"
SECRET_KEY = settings.secret_key
ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes or 60


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create JWT access token

    Expected payload format:
    {
        "sub": "username or user_id",
        "role": "admin/user",
        "type": "access"
    }
    """

    to_encode = data.copy()

    expire = datetime.utcnow() + (
        expires_delta if expires_delta
        else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access"
    })

    encoded_jwt = jwt.encode(
        to_encode,
        SECRET_KEY,
        algorithm=ALGORITHM
    )

    return encoded_jwt


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode JWT token safely
    Returns payload or None if invalid
    """
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        # basic validation
        if payload.get("type") != "access":
            return None

        return payload

    except JWTError:
        return None


def get_username_from_token(token: str) -> Optional[str]:
    """
    Extract username/user_id from token
    """
    payload = decode_access_token(token)
    if not payload:
        return None

    return payload.get("sub")


def get_role_from_token(token: str) -> Optional[str]:
    """
    Extract role from token
    """
    payload = decode_access_token(token)
    if not payload:
        return None

    return payload.get("role")


# -------------------------------------------------
# OPTIONAL: ROLE HELPERS (for future RBAC)
# -------------------------------------------------

def is_admin(token: str) -> bool:
    payload = decode_access_token(token)
    if not payload:
        return False
    return payload.get("role") == "admin"


# -------------------------------------------------
# OPTIONAL: TOKEN CREATION HELPERS
# -------------------------------------------------

def create_user_token(user_id: str, role: str = "user") -> str:
    """
    Standard login token generator
    """
    return create_access_token({
        "sub": user_id,
        "role": role
    })