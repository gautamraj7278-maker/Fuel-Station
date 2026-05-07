from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app import models, schemas
from app.routers.auth import require_admin

router = APIRouter()


def _normalize_dates(from_date: Optional[date], to_date: Optional[date]) -> tuple[date, date]:
    today = datetime.utcnow().date()
    if from_date is None and to_date is None:
        from_date = today
        to_date = today
    elif from_date is None:
        from_date = to_date
    elif to_date is None:
        to_date = from_date
    if from_date > to_date:
        from_date, to_date = to_date, from_date
    return from_date, to_date


def _date_range(start: date, end: date) -> List[date]:
    days = []
    cursor = start
    while cursor <= end:
        days.append(cursor)
        cursor = cursor + timedelta(days=1)
    return days


@router.get("/bank-accounts", response_model=List[schemas.BankAccount])
def list_bank_accounts(
    active_only: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    q = db.query(models.BankAccount)
    if active_only:
        q = q.filter(models.BankAccount.is_active == True)  # noqa: E712
    return q.order_by(models.BankAccount.account_name.asc()).all()


@router.post("/bank-accounts", response_model=schemas.BankAccount, status_code=status.HTTP_201_CREATED)
def create_bank_account(
    payload: schemas.BankAccountCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    existing = (
        db.query(models.BankAccount)
        .filter(models.BankAccount.account_name == payload.account_name)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Account name already exists")
    row = models.BankAccount(**payload.dict())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/bank-accounts/{account_id}", response_model=schemas.BankAccount)
def update_bank_account(
    account_id: int,
    payload: schemas.BankAccountUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    account = db.query(models.BankAccount).filter(models.BankAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Bank account not found")
    update_data = payload.dict(exclude_unset=True)
    if "account_name" in update_data:
        existing = (
            db.query(models.BankAccount)
            .filter(models.BankAccount.account_name == update_data["account_name"])
            .first()
        )
        if existing and existing.id != account_id:
            raise HTTPException(status_code=400, detail="Account name already exists")
    for field, value in update_data.items():
        setattr(account, field, value)
    db.commit()
    db.refresh(account)
    return account


@router.delete("/bank-accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bank_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    account = db.query(models.BankAccount).filter(models.BankAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Bank account not found")
    db.delete(account)
    db.commit()
    return None


@router.get("/expense-categories", response_model=List[schemas.ExpenseCategory])
def list_expense_categories(
    active_only: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    q = db.query(models.ExpenseCategory)
    if active_only:
        q = q.filter(models.ExpenseCategory.is_active == True)  # noqa: E712
    return q.order_by(models.ExpenseCategory.category_name.asc()).all()


@router.post("/expense-categories", response_model=schemas.ExpenseCategory, status_code=status.HTTP_201_CREATED)
def create_expense_category(
    payload: schemas.ExpenseCategoryCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    existing = (
        db.query(models.ExpenseCategory)
        .filter(models.ExpenseCategory.category_name == payload.category_name)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Expense category already exists")
    row = models.ExpenseCategory(**payload.dict())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/expense-categories/{category_id}", response_model=schemas.ExpenseCategory)
def update_expense_category(
    category_id: int,
    payload: schemas.ExpenseCategoryUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    category = db.query(models.ExpenseCategory).filter(models.ExpenseCategory.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Expense category not found")
    update_data = payload.dict(exclude_unset=True)
    if "category_name" in update_data:
        existing = (
            db.query(models.ExpenseCategory)
            .filter(models.ExpenseCategory.category_name == update_data["category_name"])
            .first()
        )
        if existing and existing.id != category_id:
            raise HTTPException(status_code=400, detail="Expense category already exists")
    for field, value in update_data.items():
        setattr(category, field, value)
    db.commit()
    db.refresh(category)
    return category


@router.delete("/expense-categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    category = db.query(models.ExpenseCategory).filter(models.ExpenseCategory.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Expense category not found")
    db.delete(category)
    db.commit()
    return None


@router.get("/cash-adjustments", response_model=List[schemas.CashAdjustment])
def list_cash_adjustments(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    from_date, to_date = _normalize_dates(from_date, to_date)
    return (
        db.query(models.CashAdjustment)
        .filter(models.CashAdjustment.business_date >= from_date, models.CashAdjustment.business_date <= to_date)
        .order_by(models.CashAdjustment.business_date.desc(), models.CashAdjustment.id.desc())
        .all()
    )


@router.post("/cash-adjustments", response_model=schemas.CashAdjustment, status_code=status.HTTP_201_CREATED)
def create_cash_adjustment(
    payload: schemas.CashAdjustmentCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    row = models.CashAdjustment(
        business_date=payload.business_date,
        amount=float(payload.amount),
        remarks=payload.remarks,
        created_by_user_id=current_user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/cash-adjustments/{adjustment_id}", response_model=schemas.CashAdjustment)
def update_cash_adjustment(
    adjustment_id: int,
    payload: schemas.CashAdjustmentUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    row = db.query(models.CashAdjustment).filter(models.CashAdjustment.id == adjustment_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Cash adjustment not found")
    update_data = payload.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/cash-adjustments/{adjustment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cash_adjustment(
    adjustment_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    row = db.query(models.CashAdjustment).filter(models.CashAdjustment.id == adjustment_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Cash adjustment not found")
    db.delete(row)
    db.commit()
    return None


@router.get("/online-allocations", response_model=List[schemas.OnlineAllocation])
def list_online_allocations(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    account_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    from_date, to_date = _normalize_dates(from_date, to_date)
    q = (
        db.query(models.OnlineAllocation)
        .filter(models.OnlineAllocation.business_date >= from_date, models.OnlineAllocation.business_date <= to_date)
    )
    if account_id is not None:
        q = q.filter(models.OnlineAllocation.account_id == account_id)
    return q.order_by(models.OnlineAllocation.business_date.desc(), models.OnlineAllocation.id.desc()).all()


@router.post("/online-allocations", response_model=schemas.OnlineAllocation, status_code=status.HTTP_201_CREATED)
def create_online_allocation(
    payload: schemas.OnlineAllocationCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    account = db.query(models.BankAccount).filter(models.BankAccount.id == payload.account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Bank account not found")
    row = models.OnlineAllocation(
        business_date=payload.business_date,
        account_id=payload.account_id,
        amount=float(payload.amount),
        remarks=payload.remarks,
        created_by_user_id=current_user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/online-allocations/{allocation_id}", response_model=schemas.OnlineAllocation)
def update_online_allocation(
    allocation_id: int,
    payload: schemas.OnlineAllocationUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    row = db.query(models.OnlineAllocation).filter(models.OnlineAllocation.id == allocation_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Online allocation not found")
    update_data = payload.dict(exclude_unset=True)
    if "account_id" in update_data:
        account = db.query(models.BankAccount).filter(models.BankAccount.id == update_data["account_id"]).first()
        if not account:
            raise HTTPException(status_code=404, detail="Bank account not found")
    for field, value in update_data.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/online-allocations/{allocation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_online_allocation(
    allocation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    row = db.query(models.OnlineAllocation).filter(models.OnlineAllocation.id == allocation_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Online allocation not found")
    db.delete(row)
    db.commit()
    return None


@router.get("/expenses", response_model=List[schemas.Expense])
def list_expenses(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    account_id: Optional[int] = Query(None),
    paid_from: Optional[schemas.ExpensePaidFrom] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    from_date, to_date = _normalize_dates(from_date, to_date)
    q = (
        db.query(models.Expense)
        .filter(models.Expense.business_date >= from_date, models.Expense.business_date <= to_date)
    )
    if account_id is not None:
        q = q.filter(models.Expense.account_id == account_id)
    if paid_from is not None:
        q = q.filter(models.Expense.paid_from == models.ExpensePaidFrom(paid_from.value))
    return q.order_by(models.Expense.business_date.desc(), models.Expense.id.desc()).all()


@router.post("/expenses", response_model=schemas.Expense, status_code=status.HTTP_201_CREATED)
def create_expense(
    payload: schemas.ExpenseCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    category = db.query(models.ExpenseCategory).filter(models.ExpenseCategory.id == payload.category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Expense category not found")
    if payload.paid_from == schemas.ExpensePaidFrom.ACCOUNT and payload.account_id is None:
        raise HTTPException(status_code=400, detail="Account is required for account expenses")
    if payload.paid_from == schemas.ExpensePaidFrom.CASH and payload.account_id is not None:
        raise HTTPException(status_code=400, detail="Account must be empty for cash expenses")
    if payload.account_id is not None:
        account = db.query(models.BankAccount).filter(models.BankAccount.id == payload.account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="Bank account not found")
    row = models.Expense(
        business_date=payload.business_date,
        category_id=payload.category_id,
        paid_from=models.ExpensePaidFrom(payload.paid_from.value),
        account_id=payload.account_id,
        amount=float(payload.amount),
        remarks=payload.remarks,
        created_by_user_id=current_user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/expenses/{expense_id}", response_model=schemas.Expense)
def update_expense(
    expense_id: int,
    payload: schemas.ExpenseUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    row = db.query(models.Expense).filter(models.Expense.id == expense_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Expense not found")
    update_data = payload.dict(exclude_unset=True)
    if "category_id" in update_data:
        category = db.query(models.ExpenseCategory).filter(models.ExpenseCategory.id == update_data["category_id"]).first()
        if not category:
            raise HTTPException(status_code=404, detail="Expense category not found")
    paid_from_raw = update_data.get("paid_from", row.paid_from)
    if isinstance(paid_from_raw, (schemas.ExpensePaidFrom, models.ExpensePaidFrom)):
        paid_from_value = paid_from_raw.value
    else:
        paid_from_value = str(paid_from_raw)
    account_id = update_data.get("account_id", row.account_id)
    if paid_from_value == schemas.ExpensePaidFrom.ACCOUNT.value and account_id is None:
        raise HTTPException(status_code=400, detail="Account is required for account expenses")
    if paid_from_value == schemas.ExpensePaidFrom.CASH.value and account_id is not None:
        raise HTTPException(status_code=400, detail="Account must be empty for cash expenses")
    if account_id is not None:
        account = db.query(models.BankAccount).filter(models.BankAccount.id == account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="Bank account not found")
    if "paid_from" in update_data:
        update_data["paid_from"] = models.ExpensePaidFrom(paid_from_value)
    for field, value in update_data.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    row = db.query(models.Expense).filter(models.Expense.id == expense_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Expense not found")
    db.delete(row)
    db.commit()
    return None


@router.get("/cash-deposits", response_model=List[schemas.CashDeposit])
def list_cash_deposits(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    account_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    from_date, to_date = _normalize_dates(from_date, to_date)
    q = (
        db.query(models.CashDeposit)
        .filter(models.CashDeposit.business_date >= from_date, models.CashDeposit.business_date <= to_date)
    )
    if account_id is not None:
        q = q.filter(models.CashDeposit.account_id == account_id)
    return q.order_by(models.CashDeposit.business_date.desc(), models.CashDeposit.id.desc()).all()


@router.post("/cash-deposits", response_model=schemas.CashDeposit, status_code=status.HTTP_201_CREATED)
def create_cash_deposit(
    payload: schemas.CashDepositCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    account = db.query(models.BankAccount).filter(models.BankAccount.id == payload.account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Bank account not found")
    row = models.CashDeposit(
        business_date=payload.business_date,
        account_id=payload.account_id,
        amount=float(payload.amount),
        remarks=payload.remarks,
        created_by_user_id=current_user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/cash-deposits/{deposit_id}", response_model=schemas.CashDeposit)
def update_cash_deposit(
    deposit_id: int,
    payload: schemas.CashDepositUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    row = db.query(models.CashDeposit).filter(models.CashDeposit.id == deposit_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Cash deposit not found")
    update_data = payload.dict(exclude_unset=True)
    if "account_id" in update_data:
        account = db.query(models.BankAccount).filter(models.BankAccount.id == update_data["account_id"]).first()
        if not account:
            raise HTTPException(status_code=404, detail="Bank account not found")
    for field, value in update_data.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/cash-deposits/{deposit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cash_deposit(
    deposit_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    row = db.query(models.CashDeposit).filter(models.CashDeposit.id == deposit_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Cash deposit not found")
    db.delete(row)
    db.commit()
    return None


@router.get("/summary", response_model=schemas.FinancialSummaryResponse)
def get_financial_summary(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    account_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _ = current_user
    from_date, to_date = _normalize_dates(from_date, to_date)

    accounts_query = db.query(models.BankAccount)
    if account_id is not None:
        accounts_query = accounts_query.filter(models.BankAccount.id == account_id)
    accounts = accounts_query.order_by(models.BankAccount.account_name.asc()).all()
    if account_id is not None and not accounts:
        raise HTTPException(status_code=404, detail="Bank account not found")
    account_ids = [a.id for a in accounts]
    account_map = {a.id: a for a in accounts}

    sale_date = func.coalesce(models.Sale.business_date, func.date(models.Sale.created_at))
    sales_rows = (
        db.query(
            sale_date.label("business_date"),
            func.sum(models.Sale.quantity).label("quantity"),
            func.sum(models.Sale.total_amount).label("amount"),
        )
        .filter(models.Sale.transaction_type == models.TransactionType.SALE)
        .group_by(sale_date)
        .all()
    )
    sales_map: Dict[str, Dict[str, float]] = {}
    for r in sales_rows:
        key = str(r.business_date)
        sales_map[key] = {
            "quantity": float(r.quantity or 0.0),
            "amount": float(r.amount or 0.0),
            "cash": 0.0,
            "online": 0.0,
        }

    legacy_deposit_rows = (
        db.query(
            sale_date.label("business_date"),
            func.sum(models.Sale.deposit_cash).label("cash"),
            func.sum(models.Sale.deposit_online).label("online"),
        )
        .filter(
            models.Sale.transaction_type == models.TransactionType.SALE,
            models.Sale.sales_batch_id.is_(None),
        )
        .group_by(sale_date)
        .all()
    )
    for r in legacy_deposit_rows:
        key = str(r.business_date)
        sales_map.setdefault(key, {"quantity": 0.0, "amount": 0.0, "cash": 0.0, "online": 0.0})
        sales_map[key]["cash"] += float(r.cash or 0.0)
        sales_map[key]["online"] += float(r.online or 0.0)

    batch_deposit_rows = (
        db.query(
            models.SalesBatch.business_date.label("business_date"),
            func.sum(models.SalesBatch.deposit_cash).label("cash"),
            func.sum(models.SalesBatch.deposit_online).label("online"),
        )
        .group_by(models.SalesBatch.business_date)
        .all()
    )
    for r in batch_deposit_rows:
        key = str(r.business_date)
        sales_map.setdefault(key, {"quantity": 0.0, "amount": 0.0, "cash": 0.0, "online": 0.0})
        sales_map[key]["cash"] += float(r.cash or 0.0)
        sales_map[key]["online"] += float(r.online or 0.0)

    cash_adj_rows = (
        db.query(
            models.CashAdjustment.business_date,
            func.sum(models.CashAdjustment.amount).label("amount"),
        )
        .group_by(models.CashAdjustment.business_date)
        .all()
    )
    cash_adj_map = {str(r.business_date): float(r.amount or 0.0) for r in cash_adj_rows}

    alloc_query = (
        db.query(
            models.OnlineAllocation.business_date,
            models.OnlineAllocation.account_id,
            func.sum(models.OnlineAllocation.amount).label("amount"),
        )
        .group_by(models.OnlineAllocation.business_date, models.OnlineAllocation.account_id)
    )
    if account_ids:
        alloc_query = alloc_query.filter(models.OnlineAllocation.account_id.in_(account_ids))
    alloc_rows = alloc_query.all()
    alloc_map: Dict[str, Dict[int, float]] = {}
    for r in alloc_rows:
        d_key = str(r.business_date)
        alloc_map.setdefault(d_key, {})
        alloc_map[d_key][int(r.account_id)] = float(r.amount or 0.0)

    deposit_query = (
        db.query(
            models.CashDeposit.business_date,
            models.CashDeposit.account_id,
            func.sum(models.CashDeposit.amount).label("amount"),
        )
        .group_by(models.CashDeposit.business_date, models.CashDeposit.account_id)
    )
    if account_ids:
        deposit_query = deposit_query.filter(models.CashDeposit.account_id.in_(account_ids))
    deposit_rows = deposit_query.all()
    deposit_map: Dict[str, Dict[int, float]] = {}
    for r in deposit_rows:
        d_key = str(r.business_date)
        deposit_map.setdefault(d_key, {})
        deposit_map[d_key][int(r.account_id)] = float(r.amount or 0.0)

    expense_query = (
        db.query(
            models.Expense.business_date,
            models.Expense.paid_from,
            models.Expense.account_id,
            func.sum(models.Expense.amount).label("amount"),
        )
        .group_by(models.Expense.business_date, models.Expense.paid_from, models.Expense.account_id)
    )
    if account_ids:
        expense_query = expense_query.filter(
            (models.Expense.account_id.is_(None)) | (models.Expense.account_id.in_(account_ids))
        )
    expense_rows = expense_query.all()
    expense_cash_map: Dict[str, float] = {}
    expense_account_map: Dict[str, Dict[int, float]] = {}
    for r in expense_rows:
        d_key = str(r.business_date)
        if r.paid_from == models.ExpensePaidFrom.CASH:
            expense_cash_map[d_key] = float(expense_cash_map.get(d_key, 0.0) + float(r.amount or 0.0))
        else:
            if r.account_id is None:
                continue
            expense_account_map.setdefault(d_key, {})
            expense_account_map[d_key][int(r.account_id)] = float(
                expense_account_map[d_key].get(int(r.account_id), 0.0) + float(r.amount or 0.0)
            )

    min_dates = []
    sales_min = db.query(func.min(sale_date)).filter(models.Sale.transaction_type == models.TransactionType.SALE).scalar()
    if sales_min is not None:
        min_dates.append(sales_min)
    batch_min = db.query(func.min(models.SalesBatch.business_date)).scalar()
    if batch_min is not None:
        min_dates.append(batch_min)
    for model_cls in (models.CashAdjustment, models.OnlineAllocation, models.Expense, models.CashDeposit):
        min_val = db.query(func.min(model_cls.business_date)).scalar()
        if min_val is not None:
            min_dates.append(min_val)
    base_start = min(min_dates) if min_dates else from_date
    seed_start = min(base_start, from_date)

    prev_cash_closing = 0.0
    prev_account_closing = {a.id: float(a.starting_balance or 0.0) for a in accounts}
    rows: List[schemas.FinancialSummaryDay] = []

    for current_date in _date_range(seed_start, to_date):
        d_key = current_date.isoformat()
        sales = sales_map.get(d_key, {"quantity": 0.0, "amount": 0.0, "cash": 0.0, "online": 0.0})
        cash_adjustments = float(cash_adj_map.get(d_key, 0.0))
        opening_cash = float(prev_cash_closing + cash_adjustments)

        online_alloc_total = sum(alloc_map.get(d_key, {}).values()) if alloc_map.get(d_key) else 0.0
        online_unallocated = float(sales["online"] - online_alloc_total)

        cash_deposit_total = sum(deposit_map.get(d_key, {}).values()) if deposit_map.get(d_key) else 0.0
        cash_expenses = float(expense_cash_map.get(d_key, 0.0))

        account_breakdown = []
        closing_accounts_total = 0.0
        opening_accounts_total = 0.0
        account_expenses_total = 0.0

        for account in accounts:
            opening_account = float(prev_account_closing.get(account.id, 0.0))
            allocated = float(alloc_map.get(d_key, {}).get(account.id, 0.0))
            deposits = float(deposit_map.get(d_key, {}).get(account.id, 0.0))
            expenses = float(expense_account_map.get(d_key, {}).get(account.id, 0.0))
            closing_account = float(opening_account + allocated + deposits - expenses)
            prev_account_closing[account.id] = closing_account

            opening_accounts_total += opening_account
            closing_accounts_total += closing_account
            account_expenses_total += expenses

            account_breakdown.append(
                schemas.FinancialSummaryAccount(
                    account_id=account.id,
                    account_name=account.account_name,
                    opening_balance=opening_account,
                    online_allocated=allocated,
                    cash_deposits=deposits,
                    expenses=expenses,
                    closing_balance=closing_account,
                )
            )

        closing_cash = float(opening_cash + float(sales["cash"]) - cash_expenses - cash_deposit_total)
        prev_cash_closing = closing_cash

        opening_total = float(opening_cash + opening_accounts_total)
        closing_total = float(closing_cash + closing_accounts_total)

        if current_date >= from_date:
            rows.append(
                schemas.FinancialSummaryDay(
                    business_date=current_date,
                    sales_quantity=float(sales["quantity"]),
                    sales_amount=float(sales["amount"]),
                    sales_cash=float(sales["cash"]),
                    sales_online=float(sales["online"]),
                    online_allocated=float(online_alloc_total),
                    online_unallocated=float(online_unallocated),
                    cash_adjustments=cash_adjustments,
                    cash_deposits=float(cash_deposit_total),
                    cash_expenses=float(cash_expenses),
                    account_expenses=float(account_expenses_total),
                    opening_cash=float(opening_cash),
                    opening_accounts=float(opening_accounts_total),
                    opening_total=float(opening_total),
                    closing_cash=float(closing_cash),
                    closing_accounts=float(closing_accounts_total),
                    closing_total=float(closing_total),
                    account_breakdown=account_breakdown,
                )
            )

    return schemas.FinancialSummaryResponse(
        from_date=from_date,
        to_date=to_date,
        accounts=[schemas.BankAccount.model_validate(a) for a in accounts],
        rows=rows,
    )
