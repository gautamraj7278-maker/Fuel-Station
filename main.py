import time
import traceback

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request

from app.database import engine, SessionLocal
from app import models
from app.auth import decode_access_token
from app.schema_migrations import (
    migrate_pumps_to_dispensers,
    migrate_add_missing_columns,
    migrate_drop_compartment_unique,
    migrate_cashier_role_to_operator,
    migrate_product_categories,
)
from app.routers import auth, sales, inventory, pumps, dispensers, customers, reports, setup, nozzles, daily_close, meters, products, product_categories, tanks, shift_config, audit, employees, designations, product_prices, tanker_receipts, bulk_upload, financial, users, tasks

# Best-effort schema migration (pumps -> dispensers)
migrate_pumps_to_dispensers(engine)

# Best-effort schema migration (add later nullable columns)
migrate_add_missing_columns(engine)

# Best-effort schema migration (allow multiple compartments per product)
migrate_drop_compartment_unique(engine)

# Best-effort schema migration (normalize legacy roles)
migrate_cashier_role_to_operator(engine)

# Best-effort schema migration (product categories)
migrate_product_categories(engine)

# Create database tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Fuel Station Management API",
    description="API for managing fuel station operations and sales",
    version="1.0.0"
)


def _should_capture_body(request: Request) -> bool:
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return False

    path = request.url.path or ""
    # Never capture credentials or setup passwords.
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
    if not token:
        return None
    try:
        return decode_access_token(token)
    except Exception:
        return None


def _write_audit_log(
    *,
    username,
    method: str,
    path: str,
    status_code: int,
    success: bool,
    duration_ms,
    ip_address,
    user_agent,
    request_body,
    error_detail,
):
    # Never block the request on audit failures.
    db = SessionLocal()
    try:
        user_id = None
        if username:
            user = db.query(models.User).filter(models.User.username == username).first()
            if user:
                user_id = user.id

        log = models.AuditLog(
            user_id=user_id,
            username=username,
            method=method,
            path=path,
            status_code=status_code,
            success=success,
            duration_ms=duration_ms,
            ip_address=ip_address,
            user_agent=user_agent,
            request_body=request_body,
            error_detail=error_detail,
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

        path = str(request.url.path)
        # Skip high-noise endpoints.
        if path not in ("/", "/health") and not path.startswith("/docs") and path != "/openapi.json":
            _write_audit_log(
                username=username,
                method=request.method,
                path=path,
                status_code=response.status_code,
                success=response.status_code < 400,
                duration_ms=duration_ms,
                ip_address=ip_address,
                user_agent=user_agent,
                request_body=body_text,
                error_detail=None,
            )
        return response
    except HTTPException as exc:
        duration_ms = (time.perf_counter() - start) * 1000.0
        detail = exc.detail
        try:
            if not isinstance(detail, str):
                detail = str(detail)
        except Exception:
            detail = "HTTPException"

        _write_audit_log(
            username=username,
            method=request.method,
            path=str(request.url.path),
            status_code=exc.status_code,
            success=False,
            duration_ms=duration_ms,
            ip_address=ip_address,
            user_agent=user_agent,
            request_body=body_text,
            error_detail=detail[:4000] if isinstance(detail, str) else None,
        )
        raise
    except Exception:
        duration_ms = (time.perf_counter() - start) * 1000.0
        _write_audit_log(
            username=username,
            method=request.method,
            path=str(request.url.path),
            status_code=500,
            success=False,
            duration_ms=duration_ms,
            ip_address=ip_address,
            user_agent=user_agent,
            request_body=body_text,
            error_detail=(traceback.format_exc()[-4000:]),
        )
        raise

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_origin_regex=r"^https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
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

@app.get("/")
def read_root():
    return {"message": "Fuel Station Management API", "version": "1.0.0"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}
