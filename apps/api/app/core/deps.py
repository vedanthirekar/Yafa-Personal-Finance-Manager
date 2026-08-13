"""Shared FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from .database import get_db
from .security import TokenError, decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]

CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    db: DbSession,
    token: Annotated[str | None, Depends(oauth2_scheme)] = None,
) -> User:
    if not token:
        raise CREDENTIALS_EXCEPTION
    return await _user_from_token(db, token)


async def _user_from_token(db: AsyncSession, token: str) -> User:
    try:
        username = decode_token(token, expected_type="access")
    except TokenError as exc:
        raise CREDENTIALS_EXCEPTION from exc

    user = await db.scalar(select(User).where(User.username == username))
    if user is None:
        # The token verified but the account is gone. Same 401 as a bad token:
        # distinguishing them would let a caller probe which usernames exist.
        raise CREDENTIALS_EXCEPTION
    return user


async def get_current_user_ws(db: AsyncSession, token: str | None) -> User | None:
    """Authenticate a WebSocket connection.

    WebSockets can't carry an Authorization header from the browser, so the
    token arrives as a query parameter. Returns None instead of raising so the
    caller can close the socket with a proper code rather than emit an HTTP
    error onto a half-open connection.
    """
    if not token:
        return None
    try:
        return await _user_from_token(db, token)
    except HTTPException:
        return None


CurrentUser = Annotated[User, Depends(get_current_user)]
