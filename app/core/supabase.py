from supabase import create_client, Client
from app.config import settings

SUPABASE_URL = settings.supabase_url
SUPABASE_KEY = settings.supabase_service_role_key

if not SUPABASE_URL or not SUPABASE_KEY:
    # During deployment/initialization, we might not have these yet
    # We create a dummy client or handle it gracefully
    supabase = None
else:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)