"""Flat, star-schema-shaped feeds for Power BI.

Power BI Desktop connects to Postgres directly via DirectQuery against the
``vw_powerbi_*`` views (see ``powerbi/sql/``). These endpoints are the
Web-connector fallback for cases where a direct database connection isn't
available -- same shapes, same column names, so the semantic model works
against either source.

Everything is flat and denormalized on purpose: Power BI builds relationships
from key columns, and nested JSON forces the user into Power Query gymnastics
before they can put a single field on a canvas.
"""

import csv
import io
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from ..core.deps import CurrentUser, DbSession
from ..models import Budget, CategoryPrediction, Merchant, Transaction
from ..services import forecasting

router = APIRouter(prefix="/powerbi", tags=["powerbi"])

Format = Query("json", pattern="^(json|csv)$")


def _respond(rows: list[dict[str, Any]], fmt: str, filename: str) -> Any:
    """Return rows as JSON, or stream them as CSV."""
    if fmt != "csv":
        return rows

    buffer = io.StringIO()
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )


@router.get("/fct_transactions")
async def fct_transactions(db: DbSession, current_user: CurrentUser, format: str = Format) -> Any:
    """Transaction fact table, one row per transaction."""
    rows = (
        await db.execute(
            select(
                Transaction.id,
                Transaction.date,
                Transaction.description,
                Transaction.category,
                Transaction.amount,
                Transaction.currency,
                Transaction.source,
                Merchant.display_name.label("merchant"),
                CategoryPrediction.confidence,
                CategoryPrediction.accepted,
                CategoryPrediction.model_version,
            )
            .select_from(Transaction)
            .outerjoin(Merchant, Merchant.id == Transaction.merchant_id)
            .outerjoin(CategoryPrediction, CategoryPrediction.transaction_id == Transaction.id)
            .where(Transaction.user_id == current_user.id)
            .order_by(Transaction.date)
        )
    ).all()

    return _respond(
        [
            {
                "transaction_key": row.id,
                "date_key": row.date.isoformat(),
                "description": row.description,
                "category_key": row.category,
                "merchant_key": row.merchant or "(unknown)",
                "amount": float(row.amount),
                "currency": row.currency,
                "source": row.source.value if hasattr(row.source, "value") else str(row.source),
                # Null for rows entered manually, which never went through the
                # model -- distinct from a prediction that scored zero.
                "categorization_confidence": (
                    float(row.confidence) if row.confidence is not None else None
                ),
                "categorization_accepted": row.accepted,
                "model_version": row.model_version,
            }
            for row in rows
        ],
        format,
        "fct_transactions",
    )


@router.get("/dim_category")
async def dim_category(db: DbSession, current_user: CurrentUser, format: str = Format) -> Any:
    """Category dimension, with the budget attached as an attribute."""
    totals = (
        await db.execute(
            select(
                Transaction.category,
                func.sum(Transaction.amount).label("total"),
                func.count(Transaction.id).label("count"),
                func.avg(Transaction.amount).label("avg_amount"),
            )
            .where(Transaction.user_id == current_user.id)
            .group_by(Transaction.category)
        )
    ).all()

    budgets = {
        row.category: row.monthly_limit
        for row in (
            await db.execute(select(Budget).where(Budget.user_id == current_user.id))
        ).scalars()
    }

    return _respond(
        [
            {
                "category_key": row.category,
                "category_name": row.category,
                "total_spend": float(row.total),
                "transaction_count": row.count,
                "avg_transaction": float(row.avg_amount),
                "monthly_budget": float(budgets[row.category]) if row.category in budgets else None,
            }
            for row in totals
        ],
        format,
        "dim_category",
    )


@router.get("/dim_merchant")
async def dim_merchant(db: DbSession, current_user: CurrentUser, format: str = Format) -> Any:
    """Merchant dimension, scoped to merchants this user actually used."""
    rows = (
        await db.execute(
            select(
                Merchant.display_name,
                Merchant.default_category,
                func.count(Transaction.id).label("count"),
                func.sum(Transaction.amount).label("total"),
            )
            .select_from(Merchant)
            .join(Transaction, Transaction.merchant_id == Merchant.id)
            .where(Transaction.user_id == current_user.id)
            .group_by(Merchant.display_name, Merchant.default_category)
            .order_by(func.sum(Transaction.amount).desc())
        )
    ).all()

    return _respond(
        [
            {
                "merchant_key": row.display_name,
                "merchant_name": row.display_name,
                "pinned_category": row.default_category,
                "transaction_count": row.count,
                "total_spend": float(row.total),
            }
            for row in rows
        ],
        format,
        "dim_merchant",
    )


@router.get("/dim_date")
async def dim_date(db: DbSession, current_user: CurrentUser, format: str = Format) -> Any:
    """Date dimension spanning the user's data.

    Power BI needs a contiguous, gap-free date table to mark as its date
    dimension -- time-intelligence DAX (MoM, YTD) is wrong without one.
    """
    bounds = (
        await db.execute(
            select(func.min(Transaction.date), func.max(Transaction.date)).where(
                Transaction.user_id == current_user.id
            )
        )
    ).one()

    start, end = bounds[0], bounds[1]
    if start is None or end is None:
        return _respond([], format, "dim_date")

    import pandas as pd

    rows = [
        {
            "date_key": stamp.date().isoformat(),
            "year": int(stamp.year),
            "quarter": f"Q{stamp.quarter}",
            "month": int(stamp.month),
            "month_name": stamp.strftime("%B"),
            "year_month": stamp.strftime("%Y-%m"),
            "day_of_week": stamp.strftime("%A"),
            "is_weekend": bool(stamp.dayofweek >= 5),
        }
        for stamp in pd.date_range(start, end, freq="D")
    ]
    return _respond(rows, format, "dim_date")


@router.get("/fct_forecast")
async def fct_forecast(
    db: DbSession,
    current_user: CurrentUser,
    steps: int = Query(6, ge=1, le=24),
    format: str = Format,
) -> Any:
    """Actual and forecast monthly spend in one table.

    Both series share a table with a ``series_type`` discriminator, so a
    single Power BI line chart can render history and projection together
    without a union step in Power Query.
    """
    df = await forecasting.load_transactions(db, current_user.id)

    rows: list[dict[str, Any]] = []
    overall = forecasting.forecast_series(df, category=None, steps=steps)

    def emit(series: Any, category: str) -> None:
        for point in series.history:
            rows.append(
                {
                    "date_key": point.date.isoformat(),
                    "category_key": category,
                    "amount": float(point.amount),
                    "lower_bound": None,
                    "upper_bound": None,
                    "series_type": "actual",
                    "model": series.model,
                    "is_fitted": series.is_fitted,
                }
            )
        for point in series.forecast:
            rows.append(
                {
                    "date_key": point.date.isoformat(),
                    "category_key": category,
                    "amount": float(point.amount),
                    "lower_bound": float(point.lower) if point.lower is not None else None,
                    "upper_bound": float(point.upper) if point.upper is not None else None,
                    "series_type": "forecast",
                    "model": series.model,
                    "is_fitted": series.is_fitted,
                }
            )

    emit(overall, "(all)")
    if not df.empty:
        for category in forecasting.top_categories(df):
            emit(
                forecasting.forecast_series(
                    df[df["category"] == category], category=category, steps=steps
                ),
                category,
            )

    return _respond(rows, format, "fct_forecast")


@router.get("/fct_anomaly")
async def fct_anomaly(db: DbSession, current_user: CurrentUser, format: str = Format) -> Any:
    """Months whose category spend sat far above that category's own norm."""
    df = await forecasting.load_transactions(db, current_user.id)
    return _respond(
        [
            {
                "date_key": a.date.isoformat(),
                "category_key": a.category,
                "amount": float(a.amount),
                "expected": float(a.expected),
                "z_score": a.z_score,
            }
            for a in forecasting.detect_anomalies(df)
        ],
        format,
        "fct_anomaly",
    )
