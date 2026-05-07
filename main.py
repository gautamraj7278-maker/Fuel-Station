import time
import traceback

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request

from app.database import engine, SessionLocal
from app import models
from app.auth import decode_access_token
from app.routers import supabase_test
from app.schema_migrations import (
    migrate_pumps_to_dispensers,
    migrate_add_missing_columns,
    migrate_drop_compartment_unique,
    migrate_cashier_role_to_operator,
    migrate_product_categories,
)
from app.routers import (
    auth, sales, inventory, pumps, dispensers, customers, reports,
    setup, nozzles, daily_close, meters, products, product_categories,
    tanks, shift_config, audit, employees, designations, product_prices,
    tanker_receipts, bulk_upload, financial, users, tasks
)

# ---------------- MIGRATIONS ----------------
migrate_pumps_to_dispensers(engine)
migrate_add_missing_columns(engine)
migrate_drop_compartment_unique(engine)
migrate_cashier_role_to_operator(engine)
migrate_product_categories(engine)

models.Base.metadata.create_all(bind=engine)

# ---------------- APP ----------------
app = FastAPI(
    title="Fuel Station Management API",
    description="API for managing fuel station operations and sales",
    version="1.0.0"
)

# ---------------- CORS (FIXED FOR DEPLOYMENT) ----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "*"   # allows deployed frontend (you can restrict later)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- ROUTERS ----------------
app.include_router(setup.router, prefix="/api/setup", tags=["Setup"])
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(sales.router, prefix="/api/sales", tags=["Sales"])
app.include_router(inventory.router, prefix="/api/inventory", tags=["Inventory"])
app.include_router(pumps.router, prefix="/api/pumps", tags=["Dispensers (legacy)"])
app.include_router(dispensers.router, prefix="/api/dispensers", tags=["Dispensers"])
app.include_router(nozzles.router, prefix="/api/nozzles", tags=["Nozzles"])
app.include_router(meters.router, prefix="/api/meters", tags=["Meters"])
app.include_router(products.router, prefix="/api/products", tags=["Products"])
app.include_router(product_prices.router, prefix="/api/product-prices", tags=["Product Prices"])
app.include_router(product_categories.router, prefix="/api/product-categories", tags=["Product Categories"])
app.include_router(tanks.router, prefix="/api/tanks", tags=["Tanks"])
app.include_router(tanker_receipts.router, prefix="/api/tanker-receipts", tags=["Tanker Receipts"])
app.include_router(bulk_upload.router, prefix="/api/bulk", tags=["Bulk Upload"])
app.include_router(shift_config.router, prefix="/api/shifts", tags=["Shifts"])
app.include_router(designations.router, prefix="/api/designations", tags=["Designations"])
app.include_router(employees.router, prefix="/api/employees", tags=["Employees"])
app.include_router(audit.router, prefix="/api/audit", tags=["Audit"])
app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(customers.router, prefix="/api/customers", tags=["Customers"])
app.include_router(reports.router, prefix="/api/reports", tags=["Reports"])
app.include_router(daily_close.router, prefix="/api/daily-close", tags=["Daily Close"])
app.include_router(financial.router, prefix="/api/financial", tags=["Financial Management"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["Tasks"])
app.include_router(supabase_test.router, prefix="/api", tags=["Supabase Test"])

# ---------------- ROOT ENDPOINTS ----------------
@app.get("/")
def read_root():
    return {"message": "Fuel Station Management API", "version": "1.0.0"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}

# ---------------- AUDIT MIDDLEWARE ----------------
def _should_capture_body(request: Request) -> bool:
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return False
    path = request.url.path or ""
    if path.startswith("/api/auth/") or path.startswith("/api/setup/"):
        return False
    content_type = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" in content_type:
        return False
    return True


def _get_username_from_request(request: Request):
    auth_header = request.headers.get("authorization") or ""
    if not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header.split(" ", 1)[1].strip()
    try:
        return decode_access_token(token)
    except Exception:
        return None


def _write_audit_log(**kwargs):
    db = SessionLocal()
    try:
        username = kwargs.get("username")
        user_id = None
        if username:
            user = db.query(models.User).filter(models.User.username == username).first()
            if user:
                user_id = user.id

        log = models.AuditLog(
            user_id=user_id,
            username=username,
            method=kwargs.get("method"),
            path=kwargs.get("path"),
            status_code=kwargs.get("status_code"),
            success=kwargs.get("success"),
            duration_ms=kwargs.get("duration_ms"),
            ip_address=kwargs.get("ip_address"),
            user_agent=kwargs.get("user_agent"),
            request_body=kwargs.get("request_body"),
            error_detail=kwargs.get("error_detail"),
        )
        db.add(log)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    start = time.perf_counter()

    username = _get_username_from_request(request)
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    body_text = None
    if _should_capture_body(request):
        try:
            raw = await request.body()
            if raw:
                body_text = raw.decode("utf-8", errors="replace")
                if len(body_text) > 2000:
                    body_text = body_text[:2000] + "…"
        except Exception:
            body_text = None

    try:
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000.0

        if request.url.path not in ("/", "/health"):
            _write_audit_log(
                username=username,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                success=response.status_code < 400,
                duration_ms=duration_ms,
                ip_address=ip_address,
                user_agent=user_agent,
                request_body=body_text,
                error_detail=None,
            )
        return response

    except Exception:
        duration_ms = (time.perf_counter() - start) * 1000.0
        _write_audit_log(
            username=username,
            method=request.method,
            path=request.url.path,
            status_code=500,
            success=False,
            duration_ms=duration_ms,
            ip_address=ip_address,
            user_agent=user_agent,
            request_body=body_text,
            error_detail=traceback.format_exc()[-4000:],
        )
        raise