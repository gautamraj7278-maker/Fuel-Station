import requests
from jose import jwt
from typing import Optional, Dict, Any

from app.config import settings


def get_user_from_supabase(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify token directly with Supabase Auth API
    """

    try:
        response = requests.get(
            f"{settings.supabase_url}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": settings.supabase_anon_key
            }
        )

        if response.status_code != 200:
            print("Supabase auth failed:", response.text)
            return None

        user_data = response.json()

        return {
            "user_id": user_data.get("id"),
            "email": user_data.get("email"),
            "role": user_data.get("role", "authenticated"),
            "raw": user_data
        }

    except Exception as e:
        print("Supabase verification error:", str(e))
        return None