from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    name: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    name: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    username: str
    email: str
    name: str


class TransactionCreate(BaseModel):
    date: date
    description: str
    category: str
    amount: float


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date
    description: str
    category: str
    amount: float
    created_at: datetime | None = None


class CategorizeRequest(BaseModel):
    text: str


class CategorizeResponse(BaseModel):
    category: str | None
    confidence: float


class VoiceTranscribeResponse(BaseModel):
    transcript: str | None
    description: str
    amount: float | None
    category: str | None
    confidence: float


class ForecastPoint(BaseModel):
    date: str
    amount: float


class ForecastResponse(BaseModel):
    history: list[ForecastPoint]
    forecast: list[ForecastPoint]


class CategoryBreakdownItem(BaseModel):
    category: str
    total_amount: float
    transaction_count: int
    pct_of_total: float
