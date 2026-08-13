from datetime import date

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import selectinload

from ..core.deps import CurrentUser, DbSession
from ..models import CategoryPrediction, Transaction
from ..schemas import (
    CategoryBreakdownItem,
    TransactionCreate,
    TransactionOut,
    TransactionPage,
    TransactionUpdate,
)
from ..schemas.voice import CorrectionRequest
from ..services import pipeline

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _to_out(transaction: Transaction) -> TransactionOut:
    """Flatten the ORM object, folding in the latest prediction's confidence."""
    latest = max(transaction.predictions, key=lambda p: p.created_at, default=None)
    return TransactionOut(
        id=transaction.id,
        date=transaction.date,
        description=transaction.description,
        category=transaction.category,
        amount=transaction.amount,
        currency=transaction.currency,
        source=transaction.source,
        merchant=transaction.merchant.display_name if transaction.merchant else None,
        raw_transcript=transaction.raw_transcript,
        created_at=transaction.created_at,
        confidence=latest.confidence if latest else None,
        was_auto_categorized=latest is not None and latest.predicted_category is not None,
    )


@router.get("", response_model=TransactionPage)
async def list_transactions(
    db: DbSession,
    current_user: CurrentUser,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    category: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    search: str | None = Query(None, max_length=200),
) -> TransactionPage:
    """Filtered, paginated transaction list.

    Paginated because the previous endpoint returned every row unbounded --
    fine at 300 rows, not fine at 300,000.
    """
    filters = [Transaction.user_id == current_user.id]
    if category:
        filters.append(Transaction.category == category)
    if start_date:
        filters.append(Transaction.date >= start_date)
    if end_date:
        filters.append(Transaction.date <= end_date)
    if search:
        filters.append(Transaction.description.ilike(f"%{search}%"))

    total = await db.scalar(select(func.count()).select_from(Transaction).where(*filters)) or 0

    rows = (
        (
            await db.scalars(
                select(Transaction)
                .where(*filters)
                .options(selectinload(Transaction.predictions))
                .order_by(Transaction.date.desc(), Transaction.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .unique()
        .all()
    )

    return TransactionPage(
        items=[_to_out(row) for row in rows], total=total, limit=limit, offset=offset
    )


@router.post("", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    payload: TransactionCreate, db: DbSession, current_user: CurrentUser
) -> TransactionOut:
    merchant = await pipeline.resolve_merchant(db, payload.merchant)

    transaction = Transaction(
        user_id=current_user.id,
        date=payload.date,
        description=payload.description,
        category=payload.category,
        amount=payload.amount,
        currency=payload.currency,
        merchant_id=merchant.id if merchant else None,
        source=payload.source,
        raw_transcript=payload.raw_transcript,
    )
    db.add(transaction)
    await db.commit()

    # Re-select with relationships loaded; the lazy-loaded `predictions` and
    # `merchant` would otherwise trigger IO during response serialization,
    # which raises on an async session.
    return _to_out(await _get_owned(db, transaction.id, current_user.id))


async def _get_owned(db: DbSession, transaction_id: int, user_id: int) -> Transaction:
    """Fetch a transaction, 404ing if it isn't this user's.

    Ownership is part of the lookup rather than a separate check, so there is
    no path that reads another user's row first and authorizes afterwards.
    """
    transaction = await db.scalar(
        select(Transaction)
        .where(Transaction.id == transaction_id, Transaction.user_id == user_id)
        .options(selectinload(Transaction.predictions))
    )
    if transaction is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    return transaction


@router.get("/{transaction_id}", response_model=TransactionOut)
async def get_transaction(
    transaction_id: int, db: DbSession, current_user: CurrentUser
) -> TransactionOut:
    return _to_out(await _get_owned(db, transaction_id, current_user.id))


@router.patch("/{transaction_id}", response_model=TransactionOut)
async def update_transaction(
    transaction_id: int, payload: TransactionUpdate, db: DbSession, current_user: CurrentUser
) -> TransactionOut:
    transaction = await _get_owned(db, transaction_id, current_user.id)

    fields = payload.model_dump(exclude_unset=True, exclude={"merchant"})
    for key, value in fields.items():
        setattr(transaction, key, value)

    if payload.merchant is not None:
        merchant = await pipeline.resolve_merchant(db, payload.merchant)
        transaction.merchant_id = merchant.id if merchant else None

    await db.commit()
    return _to_out(await _get_owned(db, transaction_id, current_user.id))


@router.post("/{transaction_id}/correct-category", response_model=TransactionOut)
async def correct_category(
    transaction_id: int, payload: CorrectionRequest, db: DbSession, current_user: CurrentUser
) -> TransactionOut:
    """Override a predicted category.

    Distinct from a plain PATCH because a correction is a labeled training
    signal, not just an edit: it marks the prediction rejected, optionally
    pins the merchant's category, and indexes a new exemplar into Qdrant.
    """
    transaction = await _get_owned(db, transaction_id, current_user.id)
    await pipeline.apply_correction(
        db,
        transaction=transaction,
        new_category=payload.category,
        remember_for_merchant=payload.remember_for_merchant,
    )
    return _to_out(await _get_owned(db, transaction_id, current_user.id))


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(transaction_id: int, db: DbSession, current_user: CurrentUser) -> None:
    await _get_owned(db, transaction_id, current_user.id)
    await db.execute(
        delete(Transaction).where(
            Transaction.id == transaction_id, Transaction.user_id == current_user.id
        )
    )
    await db.commit()


@router.get("/stats/by-category", response_model=list[CategoryBreakdownItem])
async def category_breakdown(
    db: DbSession,
    current_user: CurrentUser,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[CategoryBreakdownItem]:
    """Per-category totals.

    Aggregated in the database rather than by summing rows in Python -- the
    previous version loaded every transaction into memory to do this.
    """
    filters = [Transaction.user_id == current_user.id]
    if start_date:
        filters.append(Transaction.date >= start_date)
    if end_date:
        filters.append(Transaction.date <= end_date)

    rows = (
        await db.execute(
            select(
                Transaction.category,
                func.sum(Transaction.amount).label("total"),
                func.count(Transaction.id).label("count"),
            )
            .where(*filters)
            .group_by(Transaction.category)
            .order_by(func.sum(Transaction.amount).desc())
        )
    ).all()

    grand_total = sum(row.total for row in rows) or 0
    return [
        CategoryBreakdownItem(
            category=row.category,
            total_amount=row.total,
            transaction_count=row.count,
            pct_of_total=float(row.total / grand_total * 100) if grand_total else 0.0,
        )
        for row in rows
    ]


@router.get("/stats/categorization-quality", tags=["ops"])
async def categorization_quality(
    db: DbSession, current_user: CurrentUser
) -> dict[str, float | int]:
    """How the categorizer is doing on this user's real data.

    Acceptance rate here is a live signal, unlike the offline evaluation
    against the fixed corpus -- it measures whether users keep what the model
    suggested.
    """
    row = (
        await db.execute(
            select(
                func.count(CategoryPrediction.id).label("total"),
                func.avg(CategoryPrediction.confidence).label("avg_confidence"),
                # Postgres won't SUM a boolean, so fold it to 1/0 first.
                func.sum(case((CategoryPrediction.accepted, 1), else_=0)).label("accepted"),
            )
            .select_from(CategoryPrediction)
            .join(Transaction, Transaction.id == CategoryPrediction.transaction_id)
            .where(Transaction.user_id == current_user.id)
        )
    ).one()

    total = row.total or 0
    accepted = row.accepted or 0
    return {
        "predictions": total,
        "accepted": int(accepted),
        "acceptance_rate": round(accepted / total, 4) if total else 0.0,
        "avg_confidence": round(float(row.avg_confidence or 0.0), 4),
    }
