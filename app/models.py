from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Enum, Date, Time, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.database import Base

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    OPERATOR = "operator"
    CASHIER = "cashier"

class FuelType(str, enum.Enum):
    PETROL = "petrol"
    DIESEL = "diesel"
    PREMIUM = "premium"


class ShiftCode(str, enum.Enum):
    A = "A"
    B = "B"
    C = "C"


class TransactionType(str, enum.Enum):
    SALE = "sale"
    TESTING = "testing"

class CreditStatus(str, enum.Enum):
    PENDING = "pending"
    SETTLED = "settled"

class ExpensePaidFrom(str, enum.Enum):
    CASH = "cash"
    ACCOUNT = "account"

class TankTransferType(str, enum.Enum):
    TESTING_TO_BUFFER = "testing_to_buffer"
    BUFFER_TO_MAIN = "buffer_to_main"
    MANUAL = "manual"


class TankDipType(str, enum.Enum):
    OPENING = "opening"
    CLOSING = "closing"


class TankerReceiptStatus(str, enum.Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"

class ProductCategory(Base):
    __tablename__ = "product_categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class DeletionTargetType(str, enum.Enum):
    SALE = "sale"
    TANKER_RECEIPT = "tanker_receipt"


class DeletionRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    product_name = Column(String, unique=True, nullable=False, index=True)
    # Product category name (configurable).
    fuel_type = Column(String, nullable=False, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_deleted = Column(Boolean, default=False, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    deleted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    prices = relationship(
        "ProductPrice",
        back_populates="product",
        cascade="all, delete-orphan",
    )
    deleted_by = relationship("User", foreign_keys=[deleted_by_user_id])


class ProductPrice(Base):
    __tablename__ = "product_prices"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    price_per_liter = Column(Float, nullable=False)
    effective_date = Column(Date, nullable=False, index=True)
    remarks = Column(String)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    product = relationship("Product", back_populates="prices")
    created_by = relationship("User")


class Tank(Base):
    __tablename__ = "tanks"

    id = Column(Integer, primary_key=True, index=True)
    tank_name = Column(String, unique=True, nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    capacity = Column(Float, nullable=False)
    current_volume = Column(Float, default=0.0)
    is_buffer = Column(Boolean, default=False)
    calibration_date = Column(Date)
    calibration_due_date = Column(Date)
    remarks = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_deleted = Column(Boolean, default=False, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    deleted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    product = relationship("Product")
    calibration_points = relationship(
        "TankCalibrationPoint",
        back_populates="tank",
        cascade="all, delete-orphan",
    )
    deleted_by = relationship("User", foreign_keys=[deleted_by_user_id])


class TankCalibrationPoint(Base):
    __tablename__ = "tank_calibration_points"

    id = Column(Integer, primary_key=True, index=True)
    tank_id = Column(Integer, ForeignKey("tanks.id"), nullable=False, index=True)
    dips_mm = Column(Float, nullable=False)
    volume_in_litres = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    tank = relationship("Tank", back_populates="calibration_points")


class ShiftConfig(Base):
    __tablename__ = "shift_configs"

    id = Column(Integer, primary_key=True, index=True)
    shift = Column(Enum(ShiftCode), unique=True, nullable=False, index=True)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    is_active = Column(Boolean, default=True)
    remarks = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String)
    role = Column(Enum(UserRole), default=UserRole.OPERATOR)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    sales = relationship("Sale", back_populates="user", foreign_keys="Sale.user_id")
    operated_sales = relationship("Sale", back_populates="operator", foreign_keys="Sale.operator_id")

class Customer(Base):
    __tablename__ = "customers"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    phone = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    vehicle_number = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_deleted = Column(Boolean, default=False, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    deleted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    
    # Relationships
    sales = relationship("Sale", back_populates="customer")
    deleted_by = relationship("User", foreign_keys=[deleted_by_user_id])


class Designation(Base):
    __tablename__ = "designations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_deleted = Column(Boolean, default=False, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    deleted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    employees = relationship("Employee", back_populates="designation")
    deleted_by = relationship("User", foreign_keys=[deleted_by_user_id])


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    employee_name = Column(String, nullable=False, index=True)
    dob = Column(Date, nullable=True)
    address = Column(Text, nullable=True)
    contact_no = Column(String, nullable=True, index=True)
    id_no = Column(String, unique=True, nullable=True, index=True)
    designation_id = Column(Integer, ForeignKey("designations.id"), nullable=True, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_deleted = Column(Boolean, default=False, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    deleted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    designation = relationship("Designation", back_populates="employees")
    deleted_by = relationship("User", foreign_keys=[deleted_by_user_id])

class Dispenser(Base):
    __tablename__ = "dispensers"

    id = Column(Integer, primary_key=True, index=True)
    dispenser_number = Column(String, unique=True, nullable=False, index=True)
    fuel_type = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    last_maintenance = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_deleted = Column(Boolean, default=False, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    deleted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # Relationships
    sales = relationship("Sale", back_populates="dispenser")
    nozzles = relationship("Nozzle", back_populates="dispenser", cascade="all, delete-orphan")
    deleted_by = relationship("User", foreign_keys=[deleted_by_user_id])


class Nozzle(Base):
    __tablename__ = "nozzles"

    id = Column(Integer, primary_key=True, index=True)
    dispenser_id = Column(Integer, ForeignKey("dispensers.id"), nullable=False, index=True)
    nozzle_number = Column(String, nullable=False, index=True)
    # Keep fuel_type for compatibility, but prefer product_id.
    fuel_type = Column(String, nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True, index=True)
    tank_id = Column(Integer, ForeignKey("tanks.id"), nullable=True, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_deleted = Column(Boolean, default=False, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    deleted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    dispenser = relationship("Dispenser", back_populates="nozzles")
    product = relationship("Product")
    tank = relationship("Tank")
    meters = relationship("Meter", back_populates="nozzle", cascade="all, delete-orphan")
    deleted_by = relationship("User", foreign_keys=[deleted_by_user_id])


class Meter(Base):
    __tablename__ = "meters"

    id = Column(Integer, primary_key=True, index=True)
    nozzle_id = Column(Integer, ForeignKey("nozzles.id"), nullable=False, index=True)
    meter_name = Column(String, nullable=False)
    max_value = Column(Float, nullable=True)  # if set, meter wraps to 0 after reaching max_value
    last_reading = Column(Float, default=0.0)  # last closing reading; becomes next opening
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_deleted = Column(Boolean, default=False, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    deleted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    nozzle = relationship("Nozzle", back_populates="meters")
    deleted_by = relationship("User", foreign_keys=[deleted_by_user_id])

class FuelInventory(Base):
    __tablename__ = "fuel_inventory"
    
    id = Column(Integer, primary_key=True, index=True)
    fuel_type = Column(String, unique=True, nullable=False, index=True)
    current_stock = Column(Float, default=0.0)  # in liters
    price_per_liter = Column(Float, nullable=False)
    reorder_level = Column(Float, default=0.0)  # minimum stock level
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SalesBatch(Base):
    __tablename__ = "sales_batches"

    id = Column(Integer, primary_key=True, index=True)
    batch_code = Column(String, unique=True, index=True, nullable=False)
    dispenser_id = Column(Integer, ForeignKey("dispensers.id"), nullable=False, index=True)
    business_date = Column(Date, nullable=False, index=True)
    shift = Column(Enum(ShiftCode), default=ShiftCode.A)
    operator_employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    deposit_cash = Column(Float, nullable=False, default=0.0)
    deposit_online = Column(Float, nullable=False, default=0.0)
    deposit_credit = Column(Float, nullable=False, default=0.0)
    total_deposit = Column(Float, nullable=False, default=0.0)
    remarks = Column(String, nullable=True)
    credit_status = Column(Enum(CreditStatus), nullable=True, index=True)
    credit_settled_at = Column(DateTime, nullable=True, index=True)
    credit_settled_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    credit_notes = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    edited_at = Column(DateTime, nullable=True, index=True)
    edited_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    dispenser = relationship("Dispenser")
    operator_employee = relationship("Employee")
    created_by = relationship("User", foreign_keys=[user_id])
    edited_by = relationship("User", foreign_keys=[edited_by_user_id])
    credit_settled_by = relationship("User", foreign_keys=[credit_settled_by_user_id])
    lines = relationship("Sale", back_populates="sales_batch", cascade="all, delete-orphan")

class Sale(Base):
    __tablename__ = "sales"
    
    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(String, unique=True, index=True, nullable=False)
    dispenser_id = Column(Integer, ForeignKey("dispensers.id"), nullable=False)
    sales_batch_id = Column(Integer, ForeignKey("sales_batches.id"), nullable=True, index=True)
    nozzle_id = Column(Integer, ForeignKey("nozzles.id"), nullable=True)
    meter_id = Column(Integer, ForeignKey("meters.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Operator is a station employee (preferred for shift-closing workflow)
    operator_employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    fuel_type = Column(String, nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    quantity = Column(Float, nullable=False)  # in liters
    testing_quantity = Column(Float, nullable=True)
    opening_meter_reading = Column(Float, nullable=True)
    closing_meter_reading = Column(Float, nullable=True)
    price_per_liter = Column(Float, nullable=False)
    total_amount = Column(Float, nullable=False)
    # Deprecated: shift-closing uses deposits (cash/online) instead.
    payment_method = Column(String, default="cash")  # cash, card, upi
    # Shift-closing fields
    business_date = Column(Date, nullable=True, index=True)
    deposit_cash = Column(Float, nullable=True, default=0.0)
    deposit_online = Column(Float, nullable=True, default=0.0)
    total_deposit = Column(Float, nullable=True, default=0.0)
    remarks = Column(String, nullable=True)
    transaction_type = Column(Enum(TransactionType), default=TransactionType.SALE)
    shift = Column(Enum(ShiftCode), default=ShiftCode.A)
    edited_at = Column(DateTime, nullable=True, index=True)
    edited_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    dispenser = relationship("Dispenser", back_populates="sales")
    sales_batch = relationship("SalesBatch", back_populates="lines")
    user = relationship("User", back_populates="sales", foreign_keys=[user_id])
    customer = relationship("Customer", back_populates="sales")
    edited_by = relationship("User", foreign_keys=[edited_by_user_id])

    @property
    def edited_by_username(self):
        u = getattr(self, "edited_by", None)
        return getattr(u, "username", None) if u is not None else None
    nozzle = relationship("Nozzle")
    meter = relationship("Meter")
    product = relationship("Product")
    operator = relationship("User", back_populates="operated_sales", foreign_keys=[operator_id])
    operator_employee = relationship("Employee")


class DeletedSale(Base):
    """Soft-deleted sales are moved here before being purged."""

    __tablename__ = "deleted_sales"

    id = Column(Integer, primary_key=True, index=True)
    original_sale_id = Column(Integer, nullable=True, index=True)

    transaction_id = Column(String, index=True, nullable=False)
    dispenser_id = Column(Integer, nullable=False)
    sales_batch_id = Column(Integer, nullable=True)
    nozzle_id = Column(Integer, nullable=True)
    meter_id = Column(Integer, nullable=True)
    user_id = Column(Integer, nullable=False)
    operator_id = Column(Integer, nullable=True)
    operator_employee_id = Column(Integer, nullable=True, index=True)
    customer_id = Column(Integer, nullable=True)
    fuel_type = Column(String, nullable=False, index=True)
    product_id = Column(Integer, nullable=True)

    quantity = Column(Float, nullable=False)
    testing_quantity = Column(Float, nullable=True)
    opening_meter_reading = Column(Float, nullable=True)
    closing_meter_reading = Column(Float, nullable=True)
    price_per_liter = Column(Float, nullable=False)
    total_amount = Column(Float, nullable=False)

    business_date = Column(Date, nullable=True, index=True)
    deposit_cash = Column(Float, nullable=True, default=0.0)
    deposit_online = Column(Float, nullable=True, default=0.0)
    total_deposit = Column(Float, nullable=True, default=0.0)
    remarks = Column(String, nullable=True)
    transaction_type = Column(Enum(TransactionType), default=TransactionType.SALE)
    shift = Column(Enum(ShiftCode), default=ShiftCode.A)

    created_at = Column(DateTime, nullable=True)
    edited_at = Column(DateTime, nullable=True)
    edited_by_user_id = Column(Integer, nullable=True)

    deleted_at = Column(DateTime, default=datetime.utcnow, index=True)
    deleted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    delete_reason = Column(String, nullable=True)

    deleted_by = relationship("User", foreign_keys=[deleted_by_user_id])


class DeletedTankerReceipt(Base):
    """Soft-deleted tanker receipts are moved here before being purged."""

    __tablename__ = "deleted_tanker_receipts"

    id = Column(Integer, primary_key=True, index=True)
    original_receipt_id = Column(Integer, nullable=True, index=True)

    receipt_date = Column(Date, nullable=False, index=True)
    tanker_no = Column(String, nullable=False, index=True)
    transporter_name = Column(String, nullable=True)
    driver_name = Column(String, nullable=True)
    invoice_no = Column(String, nullable=True, index=True)
    remarks = Column(String, nullable=True)

    status = Column(Enum(TankerReceiptStatus), default=TankerReceiptStatus.DRAFT, index=True)
    confirmed_at = Column(DateTime, nullable=True)
    confirmed_by_user_id = Column(Integer, nullable=True)

    created_by_user_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=True)

    # Snapshots (JSON strings) for compartments and lines.
    compartments_json = Column(Text, nullable=True)
    lines_json = Column(Text, nullable=True)

    deleted_at = Column(DateTime, default=datetime.utcnow, index=True)
    deleted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    delete_reason = Column(String, nullable=True)

    deleted_by = relationship("User", foreign_keys=[deleted_by_user_id])


class DeletionRequest(Base):
    __tablename__ = "deletion_requests"

    id = Column(Integer, primary_key=True, index=True)
    target_type = Column(Enum(DeletionTargetType), nullable=False, index=True)
    target_id = Column(Integer, nullable=False, index=True)
    status = Column(Enum(DeletionRequestStatus), default=DeletionRequestStatus.PENDING, nullable=False, index=True)
    reason = Column(String, nullable=True)
    requested_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    requested_at = Column(DateTime, default=datetime.utcnow, index=True)
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_comment = Column(String, nullable=True)

    requested_by = relationship("User", foreign_keys=[requested_by_user_id])
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_user_id])


class DispenserShiftAssignment(Base):
    __tablename__ = "dispenser_shift_assignments"

    id = Column(Integer, primary_key=True, index=True)
    business_date = Column(Date, nullable=False, index=True)
    shift = Column(Enum(ShiftCode), nullable=False, index=True)
    dispenser_id = Column(Integer, ForeignKey("dispensers.id"), nullable=False, index=True)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    dispenser = relationship("Dispenser")
    operator = relationship("User")


class TankTransfer(Base):
    __tablename__ = "tank_transfers"

    id = Column(Integer, primary_key=True, index=True)
    from_tank_id = Column(Integer, ForeignKey("tanks.id"), nullable=False, index=True)
    to_tank_id = Column(Integer, ForeignKey("tanks.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    volume = Column(Float, nullable=False)
    transfer_type = Column(Enum(TankTransferType), default=TankTransferType.MANUAL)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    from_tank = relationship("Tank", foreign_keys=[from_tank_id])
    to_tank = relationship("Tank", foreign_keys=[to_tank_id])
    product = relationship("Product")
    user = relationship("User")


class TankDipReading(Base):
    """Physical dip-based stock readings (opening/closing) per tank per business day."""

    __tablename__ = "tank_dip_readings"
    __table_args__ = (
        UniqueConstraint("tank_id", "business_date", "dip_type", name="uq_tank_dip_day_type"),
    )

    id = Column(Integer, primary_key=True, index=True)
    tank_id = Column(Integer, ForeignKey("tanks.id"), nullable=False, index=True)
    business_date = Column(Date, nullable=False, index=True)
    dip_type = Column(Enum(TankDipType), nullable=False, index=True)

    dips_mm = Column(Float, nullable=False)
    computed_volume_litres = Column(Float, nullable=True)
    manual_volume_litres = Column(Float, nullable=True)
    is_auto = Column(Boolean, default=False)

    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    tank = relationship("Tank")
    created_by = relationship("User")


class TankStockLog(Base):
    """Audit log for changes applied to Tank.current_volume."""

    __tablename__ = "tank_stock_logs"

    id = Column(Integer, primary_key=True, index=True)
    tank_id = Column(Integer, ForeignKey("tanks.id"), nullable=False, index=True)
    action = Column(String, nullable=False, index=True)  # dip_opening, dip_closing, tanker_confirm, adjustment
    quantity = Column(Float, nullable=False)  # delta in litres (+/-)
    previous_volume = Column(Float, nullable=False)
    new_volume = Column(Float, nullable=False)
    notes = Column(String, nullable=True)

    related_receipt_id = Column(Integer, ForeignKey("tanker_receipts.id"), nullable=True, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    tank = relationship("Tank")
    created_by = relationship("User")


class TankerReceipt(Base):
    __tablename__ = "tanker_receipts"

    id = Column(Integer, primary_key=True, index=True)
    receipt_date = Column(Date, nullable=False, index=True)

    tanker_no = Column(String, nullable=False, index=True)
    transporter_name = Column(String, nullable=True)
    driver_name = Column(String, nullable=True)
    invoice_no = Column(String, nullable=True, index=True)

    # Legacy single-compartment fields (kept for backward compatibility).
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True, index=True)
    dips_invoice_mm = Column(Float, nullable=True)
    dips_site_mm = Column(Float, nullable=True)
    quantity_invoice_litres = Column(Float, nullable=True)
    density_invoice = Column(Float, nullable=True)
    density_site = Column(Float, nullable=True)
    temperature_c = Column(Float, nullable=True)
    remarks = Column(String, nullable=True)

    status = Column(Enum(TankerReceiptStatus), default=TankerReceiptStatus.DRAFT, index=True)
    confirmed_at = Column(DateTime, nullable=True)
    confirmed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    product = relationship("Product")
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    confirmed_by = relationship("User", foreign_keys=[confirmed_by_user_id])
    compartments = relationship(
        "TankerReceiptCompartment",
        back_populates="receipt",
        cascade="all, delete-orphan",
    )
    lines = relationship(
        "TankerReceiptLine",
        back_populates="receipt",
        cascade="all, delete-orphan",
    )


class TankerReceiptCompartment(Base):
    __tablename__ = "tanker_receipt_compartments"

    id = Column(Integer, primary_key=True, index=True)
    receipt_id = Column(Integer, ForeignKey("tanker_receipts.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)

    dips_invoice_mm = Column(Float, nullable=True)
    dips_site_mm = Column(Float, nullable=True)
    quantity_invoice_litres = Column(Float, nullable=True)
    density_invoice = Column(Float, nullable=True)
    density_site = Column(Float, nullable=True)
    temperature_c = Column(Float, nullable=True)
    remarks = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    receipt = relationship("TankerReceipt", back_populates="compartments")
    product = relationship("Product")


class TankerReceiptLine(Base):
    __tablename__ = "tanker_receipt_lines"

    id = Column(Integer, primary_key=True, index=True)
    receipt_id = Column(Integer, ForeignKey("tanker_receipts.id"), nullable=False, index=True)
    compartment_id = Column(Integer, ForeignKey("tanker_receipt_compartments.id"), nullable=True, index=True)
    tank_id = Column(Integer, ForeignKey("tanks.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)

    before_dips_mm = Column(Float, nullable=False)
    after_dips_mm = Column(Float, nullable=False)

    before_volume_litres = Column(Float, nullable=True)
    after_volume_litres = Column(Float, nullable=True)
    received_volume_litres = Column(Float, nullable=True)

    remarks = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    receipt = relationship("TankerReceipt", back_populates="lines")
    compartment = relationship("TankerReceiptCompartment")
    tank = relationship("Tank")
    product = relationship("Product")


class DailyClose(Base):
    __tablename__ = "daily_closes"

    id = Column(Integer, primary_key=True, index=True)
    business_date = Column(Date, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    opening_cash = Column(Float, default=0.0)
    closing_cash = Column(Float, default=0.0)
    notes = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")

class InventoryLog(Base):
    __tablename__ = "inventory_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    fuel_type = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False)  # restock, sale, adjustment
    quantity = Column(Float, nullable=False)
    previous_stock = Column(Float, nullable=False)
    new_stock = Column(Float, nullable=False)
    notes = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id = Column(Integer, primary_key=True, index=True)
    account_name = Column(String, nullable=False, unique=True, index=True)
    bank_name = Column(String, nullable=True)
    account_number = Column(String, nullable=True)
    starting_balance = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ExpenseCategory(Base):
    __tablename__ = "expense_categories"

    id = Column(Integer, primary_key=True, index=True)
    category_name = Column(String, nullable=False, unique=True, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class CashAdjustment(Base):
    __tablename__ = "cash_adjustments"

    id = Column(Integer, primary_key=True, index=True)
    business_date = Column(Date, nullable=False, index=True)
    amount = Column(Float, nullable=False)
    remarks = Column(String, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    created_by = relationship("User")


class OnlineAllocation(Base):
    __tablename__ = "online_allocations"

    id = Column(Integer, primary_key=True, index=True)
    business_date = Column(Date, nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    remarks = Column(String, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("BankAccount")
    created_by = relationship("User")


class Expense(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, index=True)
    business_date = Column(Date, nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("expense_categories.id"), nullable=False, index=True)
    paid_from = Column(Enum(ExpensePaidFrom), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True, index=True)
    amount = Column(Float, nullable=False)
    remarks = Column(String, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    category = relationship("ExpenseCategory")
    account = relationship("BankAccount")
    created_by = relationship("User")


class CashDeposit(Base):
    __tablename__ = "cash_deposits"

    id = Column(Integer, primary_key=True, index=True)
    business_date = Column(Date, nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    remarks = Column(String, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("BankAccount")
    created_by = relationship("User")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    username = Column(String, nullable=True, index=True)

    method = Column(String, nullable=False, index=True)
    path = Column(String, nullable=False, index=True)
    status_code = Column(Integer, nullable=False, index=True)
    success = Column(Boolean, default=True, index=True)
    duration_ms = Column(Float, nullable=True)

    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)

    request_body = Column(Text, nullable=True)
    error_detail = Column(Text, nullable=True)

    user = relationship("User")
