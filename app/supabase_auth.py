import requests
from jose import jwt, JWTError
from typing import Optional, Dict, Any

from app.config import settings

SUPABASE_JWKS_URL = f"{settings.supabase_url}/auth/v1/keys"

# Cache JWKS
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
    Verify Supabase JWT token
    """

    try:
        jwks = get_supabase_jwks()

        # Read token header
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        key = None

        for jwk in jwks["keys"]:
            if jwk["kid"] == kid:
                key = jwk
                break

        if not key:
            print("No matching JWKS key found")
            return None

        payload = jwt.decode(
            token,
            key,
            algorithms=["ES256"],   # IMPORTANT FIX
            audience="authenticated",
            issuer=f"{settings.supabase_url}/auth/v1"
        )

        return payload

    except JWTError as e:
        print("JWT Error:", str(e))
        return None

    except Exception as e:
        print("Verification Error:", str(e))
        return None


def get_user_from_supabase(token: str) -> Optional[Dict[str, Any]]:
    """
    Extract user details from verified token
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