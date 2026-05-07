from fastapi import APIRouter
from app.core.supabase import supabase

router = APIRouter()

@router.get("/test-supabase")
def test_supabase():
    try:
        response = supabase.table("pg_tables").select("*").limit(1).execute()

        return {
            "status": "success",
            "message": "Supabase connected successfully",
            "data": response.data
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }