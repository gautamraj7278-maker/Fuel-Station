from fastapi import APIRouter
from app.core.supabase import supabase

router = APIRouter()

@router.get("/test-supabase")
def test_supabase():
    try:
        response = supabase.table("test_connection").select("*").limit(1).execute()

        return {
            "status": "success",
            "data": response.data
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }