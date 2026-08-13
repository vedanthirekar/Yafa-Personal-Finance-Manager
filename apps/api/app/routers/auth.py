from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from ..core.config import get_settings
from ..core.deps import CurrentUser, DbSession
from ..core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from ..models import User
from ..schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from ..services import demo_seed

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.username),
        refresh_token=create_refresh_token(user.username),
        expires_in=settings.access_token_expire_minutes * 60,
        username=user.username,
        name=user.name,
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: DbSession) -> TokenResponse:
    existing = await db.scalar(
        select(User).where((User.username == payload.username) | (User.email == payload.email))
    )
    if existing is not None:
        # One message for both collisions. Saying which field matched turns
        # this endpoint into a username/email enumeration oracle.
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That username or email is already registered"
        )

    user = User(
        username=payload.username,
        email=payload.email,
        name=payload.name,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    user = await db.scalar(select(User).where(User.username == payload.username))

    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect username or password")

    # Successful login is the only moment the plaintext exists, so it's the
    # only chance to transparently upgrade a legacy bcrypt hash to argon2.
    if needs_rehash(user.hashed_password):
        user.hashed_password = hash_password(payload.password)
        await db.commit()

    return _token_response(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, db: DbSession) -> TokenResponse:
    """Exchange a refresh token for a new pair.

    ``decode_token`` enforces the token type, so an access token presented
    here is rejected rather than silently extending its own lifetime.
    """
    try:
        username = decode_token(payload.refresh_token, expected_type="refresh")
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token") from exc

    user = await db.scalar(select(User).where(User.username == username))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")

    return _token_response(user)


@router.post("/demo-login", response_model=TokenResponse)
async def demo_login(db: DbSession) -> TokenResponse:
    """One-click entry point -- no credentials.

    Wipes and reseeds the demo account so every visitor starts from the same
    dataset. Concurrent demo logins will interleave; that is acceptable for a
    demo and is why the account is flagged ``is_demo``.
    """
    user = await demo_seed.get_or_create_demo_user(db)
    await demo_seed.reset_and_seed(db, user)
    return _token_response(user)


@router.get("/me", response_model=UserOut)
async def me(current_user: CurrentUser) -> User:
    return current_user
