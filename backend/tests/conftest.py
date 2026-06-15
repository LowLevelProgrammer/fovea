import os
import pytest
from sqlalchemy import text

# Read database URL from env or fallback to a dedicated test database
db_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://fovea:fovea@localhost:5432/fovea_test")
os.environ["DATABASE_URL"] = db_url

from app.main import app
from app.db.session import engine, async_session
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
async def setup_db():
    """Clean database tables before each test and clean up connection pool."""
    async with engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE TABLE jobs, video_probe, videos, watch_paths CASCADE;")
        )
    yield
    # Dispose connection pool to ensure fresh connections for next test/event loop
    await engine.dispose()


@pytest.fixture
async def db_session():
    """Provide an async session for database manipulation in tests."""
    async with async_session() as session:
        yield session


@pytest.fixture
async def client():
    """Provide an async httpx client for testing endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
