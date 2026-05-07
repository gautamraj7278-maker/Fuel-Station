from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def _sqlite_has_column(conn, table: str, column: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info('{table}')")).fetchall()
    return any(r[1] == column for r in rows)  # (cid, name, type, notnull, dflt_value, pk)


def _generic_has_column(conn, table: str, column: str) -> bool:
    # Works for Postgres/MySQL; harmless for others that support information_schema.
    row = conn.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table_name AND column_name = :column_name
            LIMIT 1
            """
        ),
        {"table_name": table, "column_name": column},
    ).fetchone()
    return row is not None


def migrate_pumps_to_dispensers(engine: Engine) -> None:
    """Idempotent schema migration: pumps -> dispensers.

    - Renames table `pumps` -> `dispensers`
    - Renames columns:
        - dispensers.pump_number -> dispenser_number
        - nozzles.pump_id -> dispenser_id
        - sales.pump_id -> dispenser_id
        - dispenser_shift_assignments.pump_id -> dispenser_id

    This runs best-effort and is safe to call at startup.
    """

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    # Nothing to do if a fresh schema already exists.
    if "pumps" not in tables and "dispensers" in tables:
        # Still allow partial migrations (columns) below.
        pass

    with engine.begin() as conn:
        dialect = engine.dialect.name
        has_column = _sqlite_has_column if dialect == "sqlite" else _generic_has_column

        if dialect == "sqlite":
            conn.execute(text("PRAGMA foreign_keys=OFF"))

        # Table rename
        current_tables = set(inspect(conn).get_table_names())
        if "pumps" in current_tables and "dispensers" not in current_tables:
            conn.execute(text("ALTER TABLE pumps RENAME TO dispensers"))

        # Column renames (best-effort, only if old column exists)
        current_tables = set(inspect(conn).get_table_names())

        if "dispensers" in current_tables and has_column(conn, "dispensers", "pump_number") and not has_column(conn, "dispensers", "dispenser_number"):
            conn.execute(text("ALTER TABLE dispensers RENAME COLUMN pump_number TO dispenser_number"))

        if "nozzles" in current_tables and has_column(conn, "nozzles", "pump_id") and not has_column(conn, "nozzles", "dispenser_id"):
            conn.execute(text("ALTER TABLE nozzles RENAME COLUMN pump_id TO dispenser_id"))

        if "sales" in current_tables and has_column(conn, "sales", "pump_id") and not has_column(conn, "sales", "dispenser_id"):
            conn.execute(text("ALTER TABLE sales RENAME COLUMN pump_id TO dispenser_id"))

        if (
            "dispenser_shift_assignments" in current_tables
            and has_column(conn, "dispenser_shift_assignments", "pump_id")
            and not has_column(conn, "dispenser_shift_assignments", "dispenser_id")
        ):
            conn.execute(text("ALTER TABLE dispenser_shift_assignments RENAME COLUMN pump_id TO dispenser_id"))

        if dialect == "sqlite":
            conn.execute(text("PRAGMA foreign_keys=ON"))


def migrate_add_missing_columns(engine: Engine) -> None:
    """Idempotent schema migration to add newer nullable columns.

    This project uses best-effort startup migrations instead of Alembic.
    Older SQLite databases may be missing columns added later (e.g. product_id
    on nozzles, nozzle_id on sales). When missing, SELECTs will crash with
    "no such column".

    We only ever ADD nullable columns here (safe for SQLite).
    """

    with engine.begin() as conn:
        dialect = engine.dialect.name
        has_column = _sqlite_has_column if dialect == "sqlite" else _generic_has_column

        if dialect == "sqlite":
            conn.execute(text("PRAGMA foreign_keys=OFF"))

        tables = set(inspect(conn).get_table_names())

        # nozzles: product/tank mapping (nullable)
        if "nozzles" in tables:
            if not has_column(conn, "nozzles", "product_id"):
                conn.execute(text("ALTER TABLE nozzles ADD COLUMN product_id INTEGER"))
            if not has_column(conn, "nozzles", "tank_id"):
                conn.execute(text("ALTER TABLE nozzles ADD COLUMN tank_id INTEGER"))
            if not has_column(conn, "nozzles", "is_deleted"):
                conn.execute(text("ALTER TABLE nozzles ADD COLUMN is_deleted BOOLEAN DEFAULT 0"))
            if not has_column(conn, "nozzles", "deleted_at"):
                conn.execute(text("ALTER TABLE nozzles ADD COLUMN deleted_at DATETIME"))
            if not has_column(conn, "nozzles", "deleted_by_user_id"):
                conn.execute(text("ALTER TABLE nozzles ADD COLUMN deleted_by_user_id INTEGER"))

        # meters already existed in earlier versions; no migration needed here.
        if "meters" in tables:
            if not has_column(conn, "meters", "is_deleted"):
                conn.execute(text("ALTER TABLE meters ADD COLUMN is_deleted BOOLEAN DEFAULT 0"))
            if not has_column(conn, "meters", "deleted_at"):
                conn.execute(text("ALTER TABLE meters ADD COLUMN deleted_at DATETIME"))
            if not has_column(conn, "meters", "deleted_by_user_id"):
                conn.execute(text("ALTER TABLE meters ADD COLUMN deleted_by_user_id INTEGER"))

        # sales: meter-based workflow (nullable additions)
        if "sales" in tables:
            if not has_column(conn, "sales", "nozzle_id"):
                conn.execute(text("ALTER TABLE sales ADD COLUMN nozzle_id INTEGER"))
            if not has_column(conn, "sales", "meter_id"):
                conn.execute(text("ALTER TABLE sales ADD COLUMN meter_id INTEGER"))
            if not has_column(conn, "sales", "product_id"):
                conn.execute(text("ALTER TABLE sales ADD COLUMN product_id INTEGER"))
            if not has_column(conn, "sales", "operator_id"):
                conn.execute(text("ALTER TABLE sales ADD COLUMN operator_id INTEGER"))
            if not has_column(conn, "sales", "sales_batch_id"):
                conn.execute(text("ALTER TABLE sales ADD COLUMN sales_batch_id INTEGER"))
            if not has_column(conn, "sales", "opening_meter_reading"):
                conn.execute(text("ALTER TABLE sales ADD COLUMN opening_meter_reading REAL"))
            if not has_column(conn, "sales", "closing_meter_reading"):
                conn.execute(text("ALTER TABLE sales ADD COLUMN closing_meter_reading REAL"))
            if not has_column(conn, "sales", "transaction_type"):
                conn.execute(text("ALTER TABLE sales ADD COLUMN transaction_type VARCHAR"))
            if not has_column(conn, "sales", "shift"):
                conn.execute(text("ALTER TABLE sales ADD COLUMN shift VARCHAR"))
            if not has_column(conn, "sales", "testing_quantity"):
                conn.execute(text("ALTER TABLE sales ADD COLUMN testing_quantity REAL"))

            # shift-closing workflow additions (nullable)
            if not has_column(conn, "sales", "business_date"):
                conn.execute(text("ALTER TABLE sales ADD COLUMN business_date DATE"))
            if not has_column(conn, "sales", "operator_employee_id"):
                conn.execute(text("ALTER TABLE sales ADD COLUMN operator_employee_id INTEGER"))
            if not has_column(conn, "sales", "deposit_cash"):
                conn.execute(text("ALTER TABLE sales ADD COLUMN deposit_cash REAL"))
            if not has_column(conn, "sales", "deposit_online"):
                conn.execute(text("ALTER TABLE sales ADD COLUMN deposit_online REAL"))
            if not has_column(conn, "sales", "total_deposit"):
                conn.execute(text("ALTER TABLE sales ADD COLUMN total_deposit REAL"))
            if not has_column(conn, "sales", "remarks"):
                conn.execute(text("ALTER TABLE sales ADD COLUMN remarks VARCHAR"))

            # edit audit (nullable)
            if not has_column(conn, "sales", "edited_at"):
                conn.execute(text("ALTER TABLE sales ADD COLUMN edited_at DATETIME"))
            if not has_column(conn, "sales", "edited_by_user_id"):
                conn.execute(text("ALTER TABLE sales ADD COLUMN edited_by_user_id INTEGER"))

        if "sales_batches" in tables:
            if not has_column(conn, "sales_batches", "deposit_credit"):
                conn.execute(text("ALTER TABLE sales_batches ADD COLUMN deposit_credit REAL"))
            if not has_column(conn, "sales_batches", "credit_status"):
                conn.execute(text("ALTER TABLE sales_batches ADD COLUMN credit_status VARCHAR"))
            if not has_column(conn, "sales_batches", "credit_settled_at"):
                conn.execute(text("ALTER TABLE sales_batches ADD COLUMN credit_settled_at DATETIME"))
            if not has_column(conn, "sales_batches", "credit_settled_by_user_id"):
                conn.execute(text("ALTER TABLE sales_batches ADD COLUMN credit_settled_by_user_id INTEGER"))
            if not has_column(conn, "sales_batches", "credit_notes"):
                conn.execute(text("ALTER TABLE sales_batches ADD COLUMN credit_notes VARCHAR"))

        if "deleted_sales" in tables:
            if not has_column(conn, "deleted_sales", "testing_quantity"):
                conn.execute(text("ALTER TABLE deleted_sales ADD COLUMN testing_quantity REAL"))
            if not has_column(conn, "deleted_sales", "sales_batch_id"):
                conn.execute(text("ALTER TABLE deleted_sales ADD COLUMN sales_batch_id INTEGER"))

        if "products" in tables:
            if not has_column(conn, "products", "is_deleted"):
                conn.execute(text("ALTER TABLE products ADD COLUMN is_deleted BOOLEAN DEFAULT 0"))
            if not has_column(conn, "products", "deleted_at"):
                conn.execute(text("ALTER TABLE products ADD COLUMN deleted_at DATETIME"))
            if not has_column(conn, "products", "deleted_by_user_id"):
                conn.execute(text("ALTER TABLE products ADD COLUMN deleted_by_user_id INTEGER"))

        if "tanks" in tables:
            if not has_column(conn, "tanks", "is_deleted"):
                conn.execute(text("ALTER TABLE tanks ADD COLUMN is_deleted BOOLEAN DEFAULT 0"))
            if not has_column(conn, "tanks", "deleted_at"):
                conn.execute(text("ALTER TABLE tanks ADD COLUMN deleted_at DATETIME"))
            if not has_column(conn, "tanks", "deleted_by_user_id"):
                conn.execute(text("ALTER TABLE tanks ADD COLUMN deleted_by_user_id INTEGER"))

        if "dispensers" in tables:
            if not has_column(conn, "dispensers", "is_deleted"):
                conn.execute(text("ALTER TABLE dispensers ADD COLUMN is_deleted BOOLEAN DEFAULT 0"))
            if not has_column(conn, "dispensers", "deleted_at"):
                conn.execute(text("ALTER TABLE dispensers ADD COLUMN deleted_at DATETIME"))
            if not has_column(conn, "dispensers", "deleted_by_user_id"):
                conn.execute(text("ALTER TABLE dispensers ADD COLUMN deleted_by_user_id INTEGER"))

        if "customers" in tables:
            if not has_column(conn, "customers", "is_deleted"):
                conn.execute(text("ALTER TABLE customers ADD COLUMN is_deleted BOOLEAN DEFAULT 0"))
            if not has_column(conn, "customers", "deleted_at"):
                conn.execute(text("ALTER TABLE customers ADD COLUMN deleted_at DATETIME"))
            if not has_column(conn, "customers", "deleted_by_user_id"):
                conn.execute(text("ALTER TABLE customers ADD COLUMN deleted_by_user_id INTEGER"))

        if "employees" in tables:
            if not has_column(conn, "employees", "is_deleted"):
                conn.execute(text("ALTER TABLE employees ADD COLUMN is_deleted BOOLEAN DEFAULT 0"))
            if not has_column(conn, "employees", "deleted_at"):
                conn.execute(text("ALTER TABLE employees ADD COLUMN deleted_at DATETIME"))
            if not has_column(conn, "employees", "deleted_by_user_id"):
                conn.execute(text("ALTER TABLE employees ADD COLUMN deleted_by_user_id INTEGER"))

        if "designations" in tables:
            if not has_column(conn, "designations", "is_deleted"):
                conn.execute(text("ALTER TABLE designations ADD COLUMN is_deleted BOOLEAN DEFAULT 0"))
            if not has_column(conn, "designations", "deleted_at"):
                conn.execute(text("ALTER TABLE designations ADD COLUMN deleted_at DATETIME"))
            if not has_column(conn, "designations", "deleted_by_user_id"):
                conn.execute(text("ALTER TABLE designations ADD COLUMN deleted_by_user_id INTEGER"))

        if dialect == "sqlite":
            conn.execute(text("PRAGMA foreign_keys=ON"))


def migrate_drop_compartment_unique(engine: Engine) -> None:
    """Remove unique constraint on (receipt_id, product_id) for tanker_receipt_compartments."""
    with engine.begin() as conn:
        dialect = engine.dialect.name
        if dialect == "sqlite":
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            try:
                idx_rows = conn.execute(text("PRAGMA index_list('tanker_receipt_compartments')")).fetchall()
                needs_rebuild = False
                for row in idx_rows:
                    # row: (seq, name, unique, origin, partial)
                    if int(row[2]) != 1:
                        continue
                    idx_name = row[1]
                    cols = conn.execute(text(f"PRAGMA index_info('{idx_name}')")).fetchall()
                    col_names = [c[2] for c in cols]  # (seqno, cid, name)
                    if col_names == ["receipt_id", "product_id"]:
                        needs_rebuild = True
                        break

                if needs_rebuild:
                    conn.execute(
                        text(
                            """
                            CREATE TABLE tanker_receipt_compartments_new (
                                id INTEGER PRIMARY KEY,
                                receipt_id INTEGER NOT NULL,
                                product_id INTEGER NOT NULL,
                                dips_invoice_mm REAL,
                                dips_site_mm REAL,
                                quantity_invoice_litres REAL,
                                density_invoice REAL,
                                density_site REAL,
                                temperature_c REAL,
                                remarks VARCHAR,
                                created_at DATETIME
                            )
                            """
                        )
                    )
                    conn.execute(
                        text(
                            """
                            INSERT INTO tanker_receipt_compartments_new (
                                id,
                                receipt_id,
                                product_id,
                                dips_invoice_mm,
                                dips_site_mm,
                                quantity_invoice_litres,
                                density_invoice,
                                density_site,
                                temperature_c,
                                remarks,
                                created_at
                            )
                            SELECT
                                id,
                                receipt_id,
                                product_id,
                                dips_invoice_mm,
                                dips_site_mm,
                                quantity_invoice_litres,
                                density_invoice,
                                density_site,
                                temperature_c,
                                remarks,
                                created_at
                            FROM tanker_receipt_compartments
                            """
                        )
                    )
                    conn.execute(text("DROP TABLE tanker_receipt_compartments"))
                    conn.execute(text("ALTER TABLE tanker_receipt_compartments_new RENAME TO tanker_receipt_compartments"))
            finally:
                conn.execute(text("PRAGMA foreign_keys=ON"))
        else:
            try:
                conn.execute(text("ALTER TABLE tanker_receipt_compartments DROP CONSTRAINT uq_receipt_compartment_product"))
            except Exception:
                # Best-effort; database might already be updated or use a different constraint name.
                pass


def migrate_cashier_role_to_operator(engine: Engine) -> None:
    """Normalize legacy cashier role to operator."""
    with engine.begin() as conn:
        tables = set(inspect(conn).get_table_names())
        if "users" not in tables:
            return

        conn.execute(text("UPDATE users SET role = 'operator' WHERE role = 'cashier'"))


def migrate_product_categories(engine: Engine) -> None:
    """Create product_categories table and seed from existing fuel types."""
    with engine.begin() as conn:
        dialect = engine.dialect.name
        tables = set(inspect(conn).get_table_names())
        if "product_categories" not in tables:
            conn.execute(
                text(
                    """
                    CREATE TABLE product_categories (
                        id INTEGER PRIMARY KEY,
                        name VARCHAR NOT NULL UNIQUE,
                        is_active BOOLEAN DEFAULT 1,
                        created_at DATETIME
                    )
                    """
                )
            )

        # Seed categories from existing products and inventory.
        existing = conn.execute(text("SELECT name FROM product_categories")).fetchall()
        existing_names = {str(r[0]).lower() for r in existing}

        seed_names = set()
        if "products" in tables:
            for row in conn.execute(text("SELECT DISTINCT fuel_type FROM products WHERE fuel_type IS NOT NULL")).fetchall():
                seed_names.add(str(row[0]).strip().lower())
        if "fuel_inventory" in tables:
            for row in conn.execute(text("SELECT DISTINCT fuel_type FROM fuel_inventory WHERE fuel_type IS NOT NULL")).fetchall():
                seed_names.add(str(row[0]).strip().lower())

        if not seed_names and not existing_names:
            seed_names = {"petrol", "diesel", "premium"}

        for name in sorted(seed_names):
            if not name or name in existing_names:
                continue
            conn.execute(
                text("INSERT INTO product_categories (name, is_active, created_at) VALUES (:name, 1, CURRENT_TIMESTAMP)"),
                {"name": name},
            )
