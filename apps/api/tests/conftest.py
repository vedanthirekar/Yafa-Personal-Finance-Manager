"""Test fixtures.

Unit tests run against nothing external. Integration tests (marked
``@pytest.mark.integration``) need Postgres and Qdrant from the compose stack
and are skipped automatically when it isn't up, so `pytest` is always safe to
run on a cold checkout.
"""

import os
from collections.abc import AsyncIterator

import pytest

# Set before importing anything from app: Settings reads the environment at
# import time and refuses to construct without a secret.
os.environ.setdefault("YAFA_JWT_SECRET", "test-only-secret-not-used-anywhere-real-0123456789")

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings


def _stack_available() -> bool:
    """True when Postgres is reachable, so integration tests can run."""
    import socket
    from urllib.parse import urlparse

    url = urlparse(str(get_settings().database_url).replace("postgresql+asyncpg", "postgresql"))
    try:
        with socket.create_connection((url.hostname or "localhost", url.port or 5432), timeout=1):
            return True
    except OSError:
        return False


STACK_UP = _stack_available()

requires_stack = pytest.mark.skipif(
    not STACK_UP,
    reason="compose stack not running (docker compose up -d postgres qdrant redis)",
)


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    """A session that rolls back, so tests never leave rows behind."""
    from app.core.database import SessionLocal

    async with SessionLocal() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """HTTP client wired straight to the ASGI app -- no network, no server.

    Note this deliberately does NOT run the lifespan handler: loading the
    embedding and Whisper models would add ~30s to every test session. Tests
    that need the categorizer call it directly.
    """
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
async def auth_client(client: AsyncClient) -> AsyncIterator[AsyncClient]:
    """Client authenticated as a freshly-registered throwaway user."""
    import uuid

    username = f"test_{uuid.uuid4().hex[:12]}"
    response = await client.post(
        "/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "name": "Test User",
            "password": "correct-horse-battery-staple",
        },
    )
    response.raise_for_status()
    token = response.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    yield client
