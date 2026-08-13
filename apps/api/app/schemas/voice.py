from datetime import date as date_type
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class ExtractionMethod(str, Enum):
    """Which layer produced the structured fields.

    Surfaced to the client so the UI can be honest about provenance, and
    logged so the deterministic-vs-LLM split is measurable rather than assumed.
    """

    REGEX = "regex"  # digit currency patterns, e.g. "$12.50"
    WORDS = "words"  # spelled-out numbers, e.g. "twelve fifty"
    LLM = "llm"  # Claude structured-output fallback
    NONE = "none"  # nothing found


class ExtractedTransaction(BaseModel):
    """The structured shape a transcript is parsed into.

    Also used verbatim as the JSON schema handed to Claude when the
    deterministic layers fail, so the two paths cannot drift apart.
    """

    amount: Decimal | None = Field(
        default=None, description="Transaction amount as a positive decimal number"
    )
    currency: str = Field(
        default="USD", description="ISO 4217 currency code, e.g. USD, INR, EUR"
    )
    merchant: str | None = Field(
        default=None, description="Payee or store name, if one was mentioned"
    )
    description: str = Field(
        default="", description="Short human-readable description of the purchase"
    )
    date: date_type | None = Field(
        default=None, description="Transaction date if stated, else null for today"
    )


class VoiceTranscribeResponse(BaseModel):
    transcript: str
    description: str
    amount: Decimal | None
    currency: str
    merchant: str | None
    date: date_type
    category: str | None
    confidence: float
    extraction_method: ExtractionMethod


class CategorizeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class CategorizeResponse(BaseModel):
    category: str | None
    confidence: float
    # The runner-up categories, so the UI can offer a one-tap correction
    # instead of a full dropdown.
    alternatives: list["CategoryScore"] = []


class CategoryScore(BaseModel):
    category: str
    confidence: float


class CorrectionRequest(BaseModel):
    """A user overriding a predicted category.

    Feeds three things: the transaction row, the merchant's sticky default,
    and a new labeled exemplar in Qdrant.
    """

    category: str = Field(min_length=1, max_length=100)
    remember_for_merchant: bool = True


# --- WebSocket frames -------------------------------------------------------


class WSMessageType(str, Enum):
    PARTIAL = "partial"  # interim transcript, may change
    FINAL = "final"  # completed transaction
    ERROR = "error"
    READY = "ready"


class WSPartial(BaseModel):
    type: WSMessageType = WSMessageType.PARTIAL
    transcript: str


class WSFinal(BaseModel):
    type: WSMessageType = WSMessageType.FINAL
    result: VoiceTranscribeResponse


class WSError(BaseModel):
    type: WSMessageType = WSMessageType.ERROR
    detail: str


CategorizeResponse.model_rebuild()
