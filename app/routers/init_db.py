import os

from fastapi import APIRouter, HTTPException, Query
from app.database import Base, engine
from app import models  # ensures all models are loaded

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.post("/init-db")
def init_db(secret: str = Query(...)):
    expected_secret = os.getenv("INIT_DB_SECRET")

    if not expected_secret or secret != expected_secret:
        raise HTTPException(status_code=403, detail="Invalid init secret")

    Base.metadata.create_all(bind=engine)

    return {
        "status": "success",
        "message": "Database tables created successfully"
    }