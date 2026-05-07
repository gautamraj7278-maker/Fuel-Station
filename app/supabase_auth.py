# supabase_auth.py
import requests
from jose import jwt, JWTError
from typing import Optional, Dict, Any

from app.config import settings

SUPABASE_JWKS_URL = f"{settings.supabase_url}/auth/v1/keys"


# Cache JWKS keys (important for performance)
_jwks_cache = None


def get_supabase_jwks():
    global _jwks_cache

    if _jwks_cache is None:
        response = requests.get(SUPABASE_JWKS_URL)
        response.raise_for_status()
        _jwks_cache = response.json()

    return _jwks_cache


def verify_supabase_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verifies Supabase JWT token and returns payload if valid
    """

    try:
        jwks = get_supabase_jwks()

        # Decode header to get key id
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        key = None
        for k in jwks["keys"]:
            if k["kid"] == kid:
                key = k
                break

        if not key:
            return None

        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience="authenticated",
            issuer=f"{settings.supabase_url}/auth/v1"
        )

        return payload

    except JWTError:
        return None
    except Exception:
        return None


def get_user_from_supabase(token: str) -> Optional[Dict[str, Any]]:
    """
    Extract user info from Supabase token
    """
    payload = verify_supabase_token(token)

    if not payload:
        return None

    return {
        "user_id": payload.get("sub"),
        "email": payload.get("email"),
        "role": payload.get("role", "authenticated"),
        "raw": payload
    }