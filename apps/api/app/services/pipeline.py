"""Transcript -> structured, categorized transaction.

One place where the whole voice path is assembled, so the HTTP route and the
WebSocket route cannot drift apart:

    transcript
      -> deterministic extraction (regex / spoken numbers)
      -> LLM fallback, only for what that couldn't parse
      -> merchant resolution (a remembered merchant short-circuits the model)
      -> semantic categorization (BERT embedding + Qdrant kNN)
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.logging import get_logger
from ..models import Merchant, Transaction, TransactionSource
from ..models.prediction import CategoryPrediction
from ..schemas.voice import ExtractionMethod, VoiceTranscribeResponse
from . import categorizer, llm_extract, nlp_extract

settings = get_settings()
log = get_logger(__name__)


def normalize_merchant(name: str) -> str:
    """Collapse spelling variants onto one key.

    "Starbucks #4412", "STARBUCKS COFFEE" and "starbucks" should all resolve
    to the same merchant row.
    """
    import re

    cleaned = re.sub(r"[^\w\s]", " ", name.lower())
    cleaned = re.sub(r"\b\d+\b", " ", cleaned)  # store numbers
    return re.sub(r"\s+", " ", cleaned).strip()


async def resolve_merchant(db: AsyncSession, name: str | None) -> Merchant | None:
    """Find or create the merchant row for a name."""
    if not name or not (normalized := normalize_merchant(name)):
        return None

    merchant = await db.scalar(select(Merchant).where(Merchant.normalized_name == normalized))
    if merchant is None:
        merchant = Merchant(normalized_name=normalized, display_name=name.strip())
        db.add(merchant)
        await db.flush()
    return merchant


async def process_transcript(
    transcript: str,
    *,
    db: AsyncSession,
    default_currency: str = "USD",
    today: date | None = None,
) -> tuple[VoiceTranscribeResponse, Merchant | None]:
    """Parse and categorize a transcript. Does not persist anything."""
    today = today or date.today()

    result = nlp_extract.extract(transcript, default_currency=default_currency, today=today)

    amount = result.amount
    currency = result.currency
    merchant_name = result.merchant
    description = result.description
    when = result.date
    method = result.method

    # Escalate only when the cheap path came up short. An amount is the one
    # field a transaction can't be useful without.
    if amount is None and settings.llm_available:
        if llm_result := await llm_extract.extract(
            transcript, default_currency=default_currency, today=today
        ):
            if llm_result.amount is not None:
                amount = llm_result.amount
                currency = llm_result.currency or currency
                method = ExtractionMethod.LLM
            merchant_name = merchant_name or llm_result.merchant
            description = llm_result.description or description
            when = llm_result.date or when

    merchant = await resolve_merchant(db, merchant_name)

    # A merchant the user has already corrected wins outright -- their explicit
    # decision should not be re-litigated by the model on every transaction.
    if merchant is not None and merchant.default_category:
        category: str | None = merchant.default_category
        confidence = 1.0
    else:
        # Categorize on description plus merchant: "coffee" alone is ambiguous
        # in a way that "coffee Starbucks" is not.
        text = f"{description} {merchant.display_name}" if merchant else description
        category, confidence, _alternatives = await categorizer.categorize(text)

    return (
        VoiceTranscribeResponse(
            transcript=transcript,
            description=description or transcript,
            amount=amount,
            currency=currency,
            merchant=merchant.display_name if merchant else None,
            date=when,
            category=category,
            confidence=confidence,
            extraction_method=method,
        ),
        merchant,
    )


async def persist_transaction(
    db: AsyncSession,
    *,
    user_id: int,
    parsed: VoiceTranscribeResponse,
    merchant: Merchant | None,
    source: TransactionSource,
    predicted_category: str | None,
    predicted_confidence: float,
    fallback_category: str = "Uncategorized",
) -> Transaction:
    """Write the transaction and record what the model predicted.

    ``parsed.category`` is the category the *user approved*; the two
    ``predicted_*`` arguments are what the *model* originally proposed. They
    diverge whenever someone fixes a misprediction in the review step, and
    keeping them apart is the entire point of this table -- storing the user's
    choice as the prediction would report perfect accuracy forever.

    The prediction row is written even when the model returned nothing --
    a low-confidence miss is exactly the case worth being able to count later.
    """
    chosen = parsed.category or fallback_category

    transaction = Transaction(
        user_id=user_id,
        date=parsed.date,
        description=parsed.description,
        category=chosen,
        amount=parsed.amount if parsed.amount is not None else Decimal(0),
        currency=parsed.currency,
        merchant_id=merchant.id if merchant else None,
        source=source,
        raw_transcript=parsed.transcript if source is TransactionSource.VOICE else None,
    )
    db.add(transaction)
    await db.flush()

    # A null prediction is never "accepted": the model declining to guess and
    # the model guessing right are different outcomes, and folding them
    # together would inflate the acceptance rate with non-answers.
    accepted = predicted_category is not None and predicted_category == parsed.category

    db.add(
        CategoryPrediction(
            transaction_id=transaction.id,
            predicted_category=predicted_category,
            confidence=predicted_confidence,
            model_version=settings.embedding_model_version,
            accepted=accepted,
            corrected_to=None if accepted or not parsed.category else parsed.category,
        )
    )
    await db.commit()
    await db.refresh(transaction)
    return transaction


async def learn_from_correction(
    db: AsyncSession,
    *,
    transaction: Transaction,
    new_category: str,
    remember_for_merchant: bool = True,
) -> None:
    """Propagate a user's category choice into the two places it teaches.

    Split out of :func:`apply_correction` because a category can be fixed at
    two moments -- in the voice review step *before* the first save, and by
    editing an existing row *after*. Both are the same signal, so both must
    reach the merchant default and the Qdrant exemplar set. Otherwise fixing a
    misprediction would only train the model if you happened to save the wrong
    category first.
    """
    if remember_for_merchant and transaction.merchant_id:
        merchant = await db.get(Merchant, transaction.merchant_id)
        if merchant is not None:
            merchant.default_category = new_category
            await db.commit()

    # Best-effort: a Qdrant hiccup must not fail the user's edit, which is
    # already committed by this point.
    try:
        await categorizer.add_exemplar(transaction.description, new_category)
    except Exception as exc:
        log.warning("pipeline.exemplar_write_failed", error=str(exc))


async def apply_correction(
    db: AsyncSession,
    *,
    transaction: Transaction,
    new_category: str,
    remember_for_merchant: bool = True,
) -> None:
    """Record a user overriding the category on an already-saved transaction.

    Three things happen, and all three are the point of storing predictions:
    the transaction is updated, the prediction is marked rejected (so accuracy
    can be measured against real behaviour), and the corrected text is indexed
    into Qdrant as a new labeled exemplar.
    """
    old_category = transaction.category
    transaction.category = new_category

    latest = await db.scalar(
        select(CategoryPrediction)
        .where(CategoryPrediction.transaction_id == transaction.id)
        .order_by(CategoryPrediction.created_at.desc())
        .limit(1)
    )
    if latest is not None:
        latest.accepted = False
        latest.corrected_to = new_category

    await db.commit()

    await learn_from_correction(
        db,
        transaction=transaction,
        new_category=new_category,
        remember_for_merchant=remember_for_merchant,
    )

    log.info(
        "pipeline.correction_applied",
        transaction_id=transaction.id,
        from_category=old_category,
        to_category=new_category,
    )
