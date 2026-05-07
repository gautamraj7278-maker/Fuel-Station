from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator
from datetime import datetime, date, time
from typing import Optional, List, Dict, Any
from enum import Enum

# Enums
class UserRole(str, Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    OPERATOR = "operator"
    CASHIER = "cashier"

FuelType = str


class ShiftCode(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class TransactionType(str, Enum):
    SALE = "sale"
    TESTING = "testing"

class CreditStatus(str, Enum):
    PENDING = "pending"
    SETTLED = "settled"

class ExpensePaidFrom(str, Enum):
    CASH = "cash"
    ACCOUNT = "account"

class DeletionTargetType(str, Enum):
    SALE = "sale"
    TANKER_RECEIPT = "tanker_receipt"


class DeletionRequestStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# Product Schemas
class ProductBase(BaseModel):
    product_name: str
    fuel_type: FuelType
    is_active: bool = True


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    product_name: Optional[str] = None
    fuel_type: Optional[FuelType] = None
    is_active: Optional[bool] = None


class Product(ProductBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ProductCategoryBase(BaseModel):
    name: str
    is_active: bool = True


class ProductCategoryCreate(ProductCategoryBase):
    pass


class ProductCategoryUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None


class ProductCategory(ProductCategoryBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# Product Price Schemas
class ProductPriceBase(BaseModel):
    product_id: int
    price_per_liter: float = Field(gt=0)
    effective_date: Optional[date] = None
    remarks: Optional[str] = None


class ProductPriceCreate(ProductPriceBase):
    pass


class ProductPrice(ProductPriceBase):
    id: int
    effective_date: date
    created_by_user_id: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# Tank Schemas
class TankCalibrationPointBase(BaseModel):
    dips_mm: float = Field(ge=0)
    volume_in_litres: float = Field(ge=0)


class TankCalibrationPoint(TankCalibrationPointBase):
    id: int
    tank_id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TankBase(BaseModel):
    tank_name: str
    product_id: int
    capacity: float = Field(gt=0)
    current_volume: float = Field(ge=0, default=0)
    is_buffer: bool = False
    calibration_date: Optional[date] = None
    calibration_due_date: Optional[date] = None
    remarks: Optional[str] = None


class TankCreate(TankBase):
    pass


class TankUpdate(BaseModel):
    tank_name: Optional[str] = None
    product_id: Optional[int] = None
    capacity: Optional[float] = Field(None, gt=0)
    current_volume: Optional[float] = Field(None, ge=0)
    is_buffer: Optional[bool] = None
    calibration_date: Optional[date] = None
    calibration_due_date: Optional[date] = None
    remarks: Optional[str] = None


class Tank(TankBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# Tank dip (daily opening/closing) schemas
class TankDipType(str, Enum):
    OPENING = "opening"
    CLOSING = "closing"


class TankDipReadingBase(BaseModel):
    tank_id: int
    business_date: date
    dip_type: TankDipType
    dips_mm: float = Field(ge=0)
    manual_volume_litres: Optional[float] = Field(None, ge=0)


class TankDipReadingCreate(TankDipReadingBase):
    pass


class TankDipReading(TankDipReadingBase):
    id: int
    computed_volume_litres: Optional[float] = None
    is_auto: bool = False
    created_by_user_id: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TankDipDailyItem(BaseModel):
    tank_id: int
    tank_name: str
    product_id: int
    business_date: date
    opening: Optional[TankDipReading] = None
    closing: Optional[TankDipReading] = None


class ClosingRequiredResponse(BaseModel):
    required: bool
    business_date: date
    missing_tank_ids: list[int]


# Tanker receipt schemas
class TankerReceiptStatus(str, Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class TankerReceiptLineBase(BaseModel):
    tank_id: int
    before_dips_mm: float = Field(ge=0)
    after_dips_mm: float = Field(ge=0)
    remarks: Optional[str] = None


class TankerReceiptLineCreate(TankerReceiptLineBase):
    pass


class TankerReceiptLine(TankerReceiptLineBase):
    id: int
    receipt_id: int
    compartment_id: Optional[int] = None
    product_id: int
    before_volume_litres: Optional[float] = None
    after_volume_litres: Optional[float] = None
    received_volume_litres: Optional[float] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TankerReceiptCompartmentBase(BaseModel):
    product_id: int
    dips_invoice_mm: Optional[float] = Field(None, ge=0)
    dips_site_mm: Optional[float] = Field(None, ge=0)
    quantity_invoice_litres: Optional[float] = Field(None, ge=0)
    density_invoice: Optional[float] = None
    density_site: Optional[float] = None
    temperature_c: Optional[float] = None
    remarks: Optional[str] = None


class TankerReceiptCompartmentCreate(TankerReceiptCompartmentBase):
    pass


class TankerReceiptCompartment(TankerReceiptCompartmentBase):
    id: int
    receipt_id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TankerReceiptBase(BaseModel):
    receipt_date: date
    tanker_no: str
    transporter_name: Optional[str] = None
    driver_name: Optional[str] = None
    invoice_no: Optional[str] = None
    product_id: Optional[int] = None
    dips_invoice_mm: Optional[float] = Field(None, ge=0)
    dips_site_mm: Optional[float] = Field(None, ge=0)
    quantity_invoice_litres: Optional[float] = Field(None, ge=0)
    density_invoice: Optional[float] = None
    density_site: Optional[float] = None
    temperature_c: Optional[float] = None
    remarks: Optional[str] = None


class TankerReceiptCreate(TankerReceiptBase):
    compartments: list[TankerReceiptCompartmentCreate] = []
    lines: list[TankerReceiptLineCreate]


class TankerReceiptUpdate(BaseModel):
    receipt_date: Optional[date] = None
    tanker_no: Optional[str] = None
    transporter_name: Optional[str] = None
    driver_name: Optional[str] = None
    invoice_no: Optional[str] = None
    product_id: Optional[int] = None
    dips_invoice_mm: Optional[float] = Field(None, ge=0)
    dips_site_mm: Optional[float] = Field(None, ge=0)
    quantity_invoice_litres: Optional[float] = Field(None, ge=0)
    density_invoice: Optional[float] = None
    density_site: Optional[float] = None
    temperature_c: Optional[float] = None
    remarks: Optional[str] = None
    compartments: Optional[list[TankerReceiptCompartmentCreate]] = None
    lines: Optional[list[TankerReceiptLineCreate]] = None


class TankerReceipt(TankerReceiptBase):
    id: int
    status: TankerReceiptStatus
    confirmed_at: Optional[datetime] = None
    confirmed_by_user_id: Optional[str] = None
    created_by_user_id: Optional[str] = None
    created_at: datetime
    compartments: list[TankerReceiptCompartment] = []
    lines: list[TankerReceiptLine]
    model_config = ConfigDict(from_attributes=True)


# Shift timing configuration
class ShiftConfigBase(BaseModel):
    shift: ShiftCode
    start_time: time
    end_time: time
    is_active: bool = True
    remarks: Optional[str] = None


class ShiftConfigCreate(ShiftConfigBase):
    pass


class ShiftConfigUpdate(BaseModel):
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    is_active: Optional[bool] = None
    remarks: Optional[str] = None


class ShiftConfig(ShiftConfigBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# User Schemas
class UserBase(BaseModel):
    username: Optional[str] = None
    email: EmailStr
    full_name: Optional[str] = None
    role: str = "user"

class UserCreate(UserBase):
    password: Optional[str] = Field(None, min_length=6, max_length=72, description="Password (6-72 characters)")

    @field_validator("password")
    @classmethod
    def password_max_72_bytes(cls, value: Optional[str]) -> Optional[str]:
        if value and len(value.encode("utf-8")) > 72:
            raise ValueError(
                "Password is too long in bytes (max 72 bytes for bcrypt). "
                "Use a shorter password or ASCII characters."
            )
        return value


class UserAdminCreate(BaseModel):
    username: Optional[str] = None
    email: EmailStr
    full_name: Optional[str] = None
    role: str = "user"
    is_active: bool = True
    password: Optional[str] = Field(None, min_length=6, max_length=72, description="Password (6-72 characters)")

    @field_validator("password")
    @classmethod
    def admin_password_max_72_bytes(cls, value: Optional[str]) -> Optional[str]:
        if value and len(value.encode("utf-8")) > 72:
            raise ValueError(
                "Password is too long in bytes (max 72 bytes for bcrypt). "
                "Use a shorter password or ASCII characters."
            )
        return value

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class UserAdminUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class UserPasswordReset(BaseModel):
    password: str = Field(min_length=6, max_length=72, description="Password (6-72 characters)")

    @field_validator("password")
    @classmethod
    def reset_password_max_72_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError(
                "Password is too long in bytes (max 72 bytes for bcrypt). "
                "Use a shorter password or ASCII characters."
            )
        return value

class User(UserBase):
    id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

# Customer Schemas
class CustomerBase(BaseModel):
    name: str
    phone: str
    email: Optional[EmailStr] = None
    vehicle_number: Optional[str] = None

class CustomerCreate(CustomerBase):
    pass

class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    vehicle_number: Optional[str] = None

class Customer(CustomerBase):
    id: int
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# Designation Schemas
class DesignationBase(BaseModel):
    name: str
    is_active: bool = True


class DesignationCreate(DesignationBase):
    pass


class DesignationUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None


class Designation(DesignationBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# Employee Schemas
class EmployeeBase(BaseModel):
    employee_name: str
    user_id: Optional[str] = None
    dob: Optional[date] = None
    address: Optional[str] = None
    contact_no: Optional[str] = None
    id_no: Optional[str] = None
    designation_id: Optional[int] = None
    is_active: bool = True


class EmployeeCreate(EmployeeBase):
    pass


class EmployeeUpdate(BaseModel):
    employee_name: Optional[str] = None
    dob: Optional[date] = None
    address: Optional[str] = None
    contact_no: Optional[str] = None
    id_no: Optional[str] = None
    designation_id: Optional[int] = None
    is_active: Optional[bool] = None


class Employee(EmployeeBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# Dispenser Schemas
class DispenserBase(BaseModel):
    dispenser_number: str
    is_active: bool = True


class DispenserCreate(DispenserBase):
    pass


class DispenserUpdate(BaseModel):
    dispenser_number: Optional[str] = None
    is_active: Optional[bool] = None
    last_maintenance: Optional[datetime] = None


class Dispenser(DispenserBase):
    id: int
    last_maintenance: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# Fuel Inventory Schemas
class FuelInventoryBase(BaseModel):
    fuel_type: FuelType
    current_stock: float = Field(ge=0)
    price_per_liter: float = Field(ge=0)
    reorder_level: float = Field(ge=0, default=0.0)

class FuelInventoryCreate(FuelInventoryBase):
    pass

class FuelInventoryUpdate(BaseModel):
    current_stock: Optional[float] = Field(None, ge=0)
    price_per_liter: Optional[float] = Field(None, ge=0)
    reorder_level: Optional[float] = Field(None, ge=0)

class FuelInventory(FuelInventoryBase):
    id: int
    last_updated: datetime
    
    model_config = ConfigDict(from_attributes=True)


class FuelInventoryDailyStatus(BaseModel):
    fuel_type: FuelType

    opening_stock: float = 0.0
    receipts: float = 0.0
    sales: float = 0.0
    testings: float = 0.0
    buffer_returns: float = 0.0
    book_stock: float = 0.0

    physical_closing_stock: Optional[float] = None
    variance: Optional[float] = None

    price_per_liter: float = 0.0
    reorder_level: float = 0.0
    needs_reorder: bool = False
    last_updated: Optional[datetime] = None

# Sale Schemas
class SaleBase(BaseModel):
    dispenser_id: int
    sales_batch_id: Optional[int] = None
    nozzle_id: Optional[int] = None
    meter_id: Optional[int] = None
    product_id: Optional[int] = None
    fuel_type: Optional[FuelType] = None
    quantity: Optional[float] = Field(None, ge=0)
    testing_quantity: Optional[float] = Field(None, ge=0)
    closing_meter_reading: Optional[float] = Field(None, ge=0)
    business_date: Optional[date] = None
    transaction_type: TransactionType = TransactionType.SALE
    shift: ShiftCode = ShiftCode.A

    operator_employee_id: Optional[int] = None
    deposit_cash: Optional[float] = Field(None, ge=0)
    deposit_online: Optional[float] = Field(None, ge=0)
    remarks: Optional[str] = None

class SaleCreate(SaleBase):
    pass


class SaleUpdate(BaseModel):
    business_date: Optional[date] = None
    shift: Optional[ShiftCode] = None
    operator_employee_id: Optional[int] = None
    deposit_cash: Optional[float] = Field(None, ge=0)
    deposit_online: Optional[float] = Field(None, ge=0)
    remarks: Optional[str] = None
    # Editing sales data:
    # - If meter_id is set, update closing_meter_reading (quantity is recomputed).
    # - If meter_id is not set, update quantity.
    closing_meter_reading: Optional[float] = Field(None, ge=0)
    quantity: Optional[float] = Field(None, ge=0)
    testing_quantity: Optional[float] = Field(None, ge=0)

class Sale(SaleBase):
    id: int
    transaction_id: str
    user_id: str
    operator_id: Optional[str] = None
    edited_at: Optional[datetime] = None
    edited_by_user_id: Optional[str] = None
    edited_by_username: Optional[str] = None
    total_deposit: Optional[float] = None
    opening_meter_reading: Optional[float] = None
    closing_meter_reading: Optional[float] = None
    price_per_liter: float
    total_amount: float
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class SalesBatchLineCreate(BaseModel):
    nozzle_id: Optional[int] = None
    meter_id: Optional[int] = None
    closing_meter_reading: Optional[float] = Field(None, ge=0)
    quantity: Optional[float] = Field(None, ge=0)
    testing_quantity: Optional[float] = Field(None, ge=0)


class SalesBatchCreate(BaseModel):
    dispenser_id: int
    business_date: Optional[date] = None
    shift: Optional[ShiftCode] = None
    operator_employee_id: Optional[int] = None
    deposit_cash: Optional[float] = Field(0, ge=0)
    deposit_online: Optional[float] = Field(0, ge=0)
    deposit_credit: Optional[float] = Field(0, ge=0)
    remarks: Optional[str] = None
    lines: List[SalesBatchLineCreate]


class SalesBatchUpdate(BaseModel):
    operator_employee_id: Optional[int] = None
    deposit_cash: Optional[float] = Field(None, ge=0)
    deposit_online: Optional[float] = Field(None, ge=0)
    deposit_credit: Optional[float] = Field(None, ge=0)
    remarks: Optional[str] = None


class SalesBatch(BaseModel):
    id: int
    batch_code: str
    dispenser_id: int
    business_date: date
    shift: ShiftCode
    operator_employee_id: Optional[int] = None
    user_id: str
    deposit_cash: float = 0.0
    deposit_online: float = 0.0
    deposit_credit: float = 0.0
    total_deposit: float = 0.0
    remarks: Optional[str] = None
    credit_status: Optional[CreditStatus] = None
    credit_settled_at: Optional[datetime] = None
    credit_settled_by_user_id: Optional[str] = None
    credit_notes: Optional[str] = None
    created_at: datetime
    edited_at: Optional[datetime] = None
    edited_by_user_id: Optional[str] = None
    lines: List[Sale] = []

    model_config = ConfigDict(from_attributes=True)


class SalesCreditEntry(BaseModel):
    id: int
    batch_code: str
    dispenser_id: int
    business_date: date
    shift: ShiftCode
    operator_employee_id: Optional[int] = None
    user_id: str
    deposit_cash: float = 0.0
    deposit_online: float = 0.0
    deposit_credit: float = 0.0
    remarks: Optional[str] = None
    credit_status: Optional[CreditStatus] = None
    credit_settled_at: Optional[datetime] = None
    credit_settled_by_user_id: Optional[str] = None
    credit_notes: Optional[str] = None
    created_at: datetime
    edited_at: Optional[datetime] = None
    edited_by_user_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class SalesCreditUpdate(BaseModel):
    credit_status: CreditStatus
    credit_settled_at: Optional[datetime] = None
    credit_notes: Optional[str] = None


class DeletedSaleBase(BaseModel):
    original_sale_id: Optional[int] = None
    transaction_id: str
    dispenser_id: int
    sales_batch_id: Optional[int] = None
    nozzle_id: Optional[int] = None
    meter_id: Optional[int] = None
    user_id: str
    operator_id: Optional[str] = None
    operator_employee_id: Optional[int] = None
    customer_id: Optional[int] = None
    fuel_type: FuelType
    product_id: Optional[int] = None
    quantity: float
    testing_quantity: Optional[float] = None
    opening_meter_reading: Optional[float] = None
    closing_meter_reading: Optional[float] = None
    price_per_liter: float
    total_amount: float
    business_date: Optional[date] = None
    deposit_cash: Optional[float] = None
    deposit_online: Optional[float] = None
    total_deposit: Optional[float] = None
    remarks: Optional[str] = None
    transaction_type: TransactionType
    shift: ShiftCode
    created_at: Optional[datetime] = None
    edited_at: Optional[datetime] = None
    edited_by_user_id: Optional[str] = None


class DeletedSale(DeletedSaleBase):
    id: int
    deleted_at: datetime
    deleted_by_user_id: Optional[str] = None
    delete_reason: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class DeletedTankerReceiptBase(BaseModel):
    original_receipt_id: Optional[int] = None

    receipt_date: date
    tanker_no: str
    transporter_name: Optional[str] = None
    driver_name: Optional[str] = None
    invoice_no: Optional[str] = None
    remarks: Optional[str] = None

    status: TankerReceiptStatus
    confirmed_at: Optional[datetime] = None
    confirmed_by_user_id: Optional[str] = None
    created_by_user_id: Optional[str] = None
    created_at: Optional[datetime] = None

    compartments_json: Optional[str] = None
    lines_json: Optional[str] = None


class DeletedTankerReceipt(DeletedTankerReceiptBase):
    id: int
    deleted_at: datetime
    deleted_by_user_id: Optional[str] = None
    delete_reason: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class DeletionRequestReview(BaseModel):
    comment: Optional[str] = Field(None, max_length=200)


class DeletionRequest(BaseModel):
    id: int
    target_type: DeletionTargetType
    target_id: int
    status: DeletionRequestStatus
    reason: Optional[str] = None
    requested_by_user_id: str
    requested_by_username: Optional[str] = None
    requested_at: datetime
    reviewed_by_user_id: Optional[str] = None
    reviewed_by_username: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_comment: Optional[str] = None
    target_label: Optional[str] = None
    target_meta: Dict[str, Any] = {}
    model_config = ConfigDict(from_attributes=True)


# Nozzle Schemas
class NozzleBase(BaseModel):
    dispenser_id: int
    nozzle_number: str
    fuel_type: Optional[FuelType] = None
    product_id: Optional[int] = None
    tank_id: Optional[int] = None
    is_active: bool = True


# Audit Log Schemas
class AuditLog(BaseModel):
    id: int
    created_at: datetime
    user_id: Optional[str] = None
    username: Optional[str] = None

    method: str
    path: str
    status_code: int
    success: bool
    duration_ms: Optional[float] = None

    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

    request_body: Optional[str] = None
    error_detail: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class NozzleCreate(NozzleBase):
    pass


class NozzleUpdate(BaseModel):
    nozzle_number: Optional[str] = None
    fuel_type: Optional[FuelType] = None
    product_id: Optional[int] = None
    tank_id: Optional[int] = None
    is_active: Optional[bool] = None


class Nozzle(NozzleBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# Meter Schemas
class MeterBase(BaseModel):
    nozzle_id: int
    meter_name: str
    max_value: Optional[float] = Field(None, gt=0)
    last_reading: float = Field(0, ge=0)
    is_active: bool = True


class MeterCreate(MeterBase):
    pass


class MeterUpdate(BaseModel):
    meter_name: Optional[str] = None
    max_value: Optional[float] = Field(None, gt=0)
    last_reading: Optional[float] = Field(None, ge=0)
    is_active: Optional[bool] = None


class Meter(MeterBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# Daily Close Schemas
class DailyCloseBase(BaseModel):
    business_date: date
    opening_cash: float = Field(ge=0)
    closing_cash: float = Field(ge=0)
    notes: Optional[str] = None


class DailyCloseCreate(DailyCloseBase):
    pass


# Shift assignment schemas
class DispenserShiftAssignmentBase(BaseModel):
    business_date: date
    shift: ShiftCode
    dispenser_id: int
    operator_id: str


class DispenserShiftAssignmentCreate(DispenserShiftAssignmentBase):
    pass


class DispenserShiftAssignment(DispenserShiftAssignmentBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# Tank transfer schemas
class TankTransferType(str, Enum):
    TESTING_TO_BUFFER = "testing_to_buffer"
    BUFFER_TO_MAIN = "buffer_to_main"
    MANUAL = "manual"


class TankTransferBase(BaseModel):
    from_tank_id: int
    to_tank_id: int
    product_id: int
    volume: float = Field(gt=0)
    transfer_type: TankTransferType = TankTransferType.MANUAL


class TankTransferCreate(TankTransferBase):
    pass


class TankTransfer(TankTransferBase):
    id: int
    user_id: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TestingReturnToMainRequest(BaseModel):
    volume: float = Field(gt=0)
    to_tank_id: Optional[int] = None


class TankComputedVolume(BaseModel):
    tank_id: int
    dips_mm: float
    volume_litres: float


class DailyClose(DailyCloseBase):
    id: int
    user_id: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# Inventory Log Schemas
class InventoryLogBase(BaseModel):
    fuel_type: FuelType
    action: str
    quantity: float
    notes: Optional[str] = None

class InventoryLog(InventoryLogBase):
    id: int
    previous_stock: float
    new_stock: float
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

# Financial Management Schemas
class BankAccountBase(BaseModel):
    account_name: str
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    starting_balance: float = Field(0, ge=0)
    is_active: bool = True


class BankAccountCreate(BankAccountBase):
    pass


class BankAccountUpdate(BaseModel):
    account_name: Optional[str] = None
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    starting_balance: Optional[float] = Field(None, ge=0)
    is_active: Optional[bool] = None


class BankAccount(BankAccountBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ExpenseCategoryBase(BaseModel):
    category_name: str
    is_active: bool = True


class ExpenseCategoryCreate(ExpenseCategoryBase):
    pass


class ExpenseCategoryUpdate(BaseModel):
    category_name: Optional[str] = None
    is_active: Optional[bool] = None


class ExpenseCategory(ExpenseCategoryBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CashAdjustmentBase(BaseModel):
    business_date: date
    amount: float
    remarks: Optional[str] = None


class CashAdjustmentCreate(CashAdjustmentBase):
    pass


class CashAdjustmentUpdate(BaseModel):
    business_date: Optional[date] = None
    amount: Optional[float] = None
    remarks: Optional[str] = None


class CashAdjustment(CashAdjustmentBase):
    id: int
    created_by_user_id: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class OnlineAllocationBase(BaseModel):
    business_date: date
    account_id: int
    amount: float = Field(gt=0)
    remarks: Optional[str] = None


class OnlineAllocationCreate(OnlineAllocationBase):
    pass


class OnlineAllocationUpdate(BaseModel):
    business_date: Optional[date] = None
    account_id: Optional[int] = None
    amount: Optional[float] = Field(None, gt=0)
    remarks: Optional[str] = None


class OnlineAllocation(OnlineAllocationBase):
    id: int
    created_by_user_id: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ExpenseBase(BaseModel):
    business_date: date
    category_id: int
    paid_from: ExpensePaidFrom
    account_id: Optional[int] = None
    amount: float = Field(gt=0)
    remarks: Optional[str] = None


class ExpenseCreate(ExpenseBase):
    pass


class ExpenseUpdate(BaseModel):
    business_date: Optional[date] = None
    category_id: Optional[int] = None
    paid_from: Optional[ExpensePaidFrom] = None
    account_id: Optional[int] = None
    amount: Optional[float] = Field(None, gt=0)
    remarks: Optional[str] = None


class Expense(ExpenseBase):
    id: int
    created_by_user_id: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CashDepositBase(BaseModel):
    business_date: date
    account_id: int
    amount: float = Field(gt=0)
    remarks: Optional[str] = None


class CashDepositCreate(CashDepositBase):
    pass


class CashDepositUpdate(BaseModel):
    business_date: Optional[date] = None
    account_id: Optional[int] = None
    amount: Optional[float] = Field(None, gt=0)
    remarks: Optional[str] = None


class CashDeposit(CashDepositBase):
    id: int
    created_by_user_id: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class FinancialSummaryAccount(BaseModel):
    account_id: int
    account_name: str
    opening_balance: float
    online_allocated: float
    cash_deposits: float
    expenses: float
    closing_balance: float


class FinancialSummaryDay(BaseModel):
    business_date: date
    sales_quantity: float
    sales_amount: float
    sales_cash: float
    sales_online: float
    online_allocated: float
    online_unallocated: float
    cash_adjustments: float
    cash_deposits: float
    cash_expenses: float
    account_expenses: float
    opening_cash: float
    opening_accounts: float
    opening_total: float
    closing_cash: float
    closing_accounts: float
    closing_total: float
    account_breakdown: List[FinancialSummaryAccount] = []


class FinancialSummaryResponse(BaseModel):
    from_date: date
    to_date: date
    accounts: List[BankAccount]
    rows: List[FinancialSummaryDay]

# Auth Schemas
class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class LoginRequest(BaseModel):
    username: str
    password: str


# Deleted records (generic)
class DeletedItem(BaseModel):
    id: int
    label: str
    deleted_at: datetime
    deleted_by_user_id: Optional[int] = None
    deleted_by_username: Optional[str] = None

# Bulk Upload (Backfill)
class BulkRowError(BaseModel):
    row: int
    message: str


class SalesBulkPreviewResponse(BaseModel):
    columns: List[str]
    total_rows: int
    valid_rows: int
    errors: List[BulkRowError] = []
    rows: List[Dict[str, Any]] = []


class BulkPreviewResponse(BaseModel):
    columns: List[str]
    total_rows: int
    valid_rows: int
    errors: List[BulkRowError] = []
    rows: List[Dict[str, Any]] = []


class BulkCommitMode(str, Enum):
    UPSERT = "upsert"
    INSERT_ONLY = "insert_only"
    UPDATE_ONLY = "update_only"


class BulkCommitRequest(BaseModel):
    rows: List[Dict[str, Any]]
    mode: BulkCommitMode = BulkCommitMode.UPSERT
    allow_partial: bool = False


class BulkCommitResponse(BaseModel):
    inserted: int
    updated: int
    failed: int


class SalesBulkCommitMode(str, Enum):
    UPSERT = "upsert"
    INSERT_ONLY = "insert_only"
    UPDATE_ONLY = "update_only"


class SalesBulkCommitRequest(BaseModel):
    rows: List[Dict[str, Any]]
    mode: SalesBulkCommitMode = SalesBulkCommitMode.UPSERT
    allow_partial: bool = False


class SalesBulkCommitResponse(BaseModel):
    inserted: int
    updated: int
    failed: int
