from pathlib import Path

from pydantic_settings import BaseSettings


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):

    # -------------------------------------------------
    # APP SETTINGS
    # -------------------------------------------------
    app_name: str = "Fuel Station Management"

    # -------------------------------------------------
    # DATABASE
    # -------------------------------------------------
    database_url: str

    # -------------------------------------------------
    # JWT SETTINGS
    # -------------------------------------------------
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # -------------------------------------------------
    # SUPABASE SETTINGS
    # -------------------------------------------------
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str = ""

    class Config:
        env_file = str(BASE_DIR / ".env")
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()