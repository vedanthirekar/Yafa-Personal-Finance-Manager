import csv
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import models, security
from ..database import get_db
from ..services.forecasting import forecast_expenses, load_transactions_dataframe

router = APIRouter(prefix="/export", tags=["export"])


def _csv_response(rows: list[dict], fieldnames: list[str]) -> StreamingResponse:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="text/csv")


@router.get("/transactions")
def export_transactions(
    format: str = Query("json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(security.get_current_user),
):
    """Flat transaction rows, consumable by Power BI's Web/CSV connector."""
    txns = (
        db.query(models.Transaction)
        .filter(models.Transaction.user_id == current_user.id)
        .order_by(models.Transaction.date)
        .all()
    )
    rows = [
        {
            "date": t.date.isoformat(),
            "description": t.description,
            "category": t.category,
            "amount": t.amount,
        }
        for t in txns
    ]
    if format == "csv":
        return _csv_response(rows, ["date", "description", "category", "amount"])
    return rows


@router.get("/category-breakdown")
def export_category_breakdown(
    format: str = Query("json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(security.get_current_user),
):
    """Aggregated per-category totals -- feeds the semantic-categorization visualization."""
    txns = (
        db.query(models.Transaction)
        .filter(models.Transaction.user_id == current_user.id)
        .all()
    )
    totals: dict[str, dict] = {}
    grand_total = 0.0
    for t in txns:
        entry = totals.setdefault(t.category, {"total_amount": 0.0, "transaction_count": 0})
        entry["total_amount"] += t.amount
        entry["transaction_count"] += 1
        grand_total += t.amount

    rows = [
        {
            "category": category,
            "total_amount": data["total_amount"],
            "transaction_count": data["transaction_count"],
            "pct_of_total": (data["total_amount"] / grand_total * 100) if grand_total else 0.0,
        }
        for category, data in totals.items()
    ]
    if format == "csv":
        return _csv_response(
            rows, ["category", "total_amount", "transaction_count", "pct_of_total"]
        )
    return rows


@router.get("/forecast")
def export_forecast(
    format: str = Query("json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(security.get_current_user),
):
    """Flattened actual + forecast rows -- feeds the time-series visualization."""
    df = load_transactions_dataframe(db, current_user.id)
    result = forecast_expenses(df) if not df.empty else None

    rows = []
    if result:
        rows += [{"date": p["date"], "amount": p["amount"], "type": "actual"} for p in result["history"]]
        rows += [
            {"date": p["date"], "amount": p["amount"], "type": "forecast"} for p in result["forecast"]
        ]
    if format == "csv":
        return _csv_response(rows, ["date", "amount", "type"])
    return rows
