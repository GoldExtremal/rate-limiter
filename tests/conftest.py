import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import asyncpg
import httpx
import pytest
from asgi_lifespan import LifespanManager
from redis.asyncio import Redis

from app.config import Settings
from app.instance import InstanceIdASGI
from app.main import create_app
from app.migrate import apply_migrations, load_migrations

TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://ratelimiter:local-dev-only@localhost:5432/ratelimiter_test"
)

ClientFactory = Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]


def make_client(app: InstanceIdASGI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@asynccontextmanager
async def running_client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = InstanceIdASGI(create_app(settings), settings.instance_id)
    async with LifespanManager(app), make_client(app) as client:
        yield client


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    client = Redis.from_url(TEST_REDIS_URL)
    await client.flushdb()
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()


async def ensure_test_database() -> None:
    database_name = TEST_DATABASE_URL.rsplit("/", 1)[1]
    admin = await asyncpg.connect(TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres")
    try:
        exists = await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", database_name)
        if not exists:
            await admin.execute(f'CREATE DATABASE "{database_name}"')
    finally:
        await admin.close()


@pytest.fixture
async def database() -> AsyncIterator[asyncpg.Connection]:
    await ensure_test_database()
    connection = await asyncpg.connect(TEST_DATABASE_URL)
    await apply_migrations(connection, load_migrations())
    await connection.execute("TRUNCATE client_limits")
    try:
        yield connection
    finally:
        await connection.close()


@pytest.fixture
def app_client(redis: Redis, database: asyncpg.Connection) -> ClientFactory:
    def factory(**overrides: Any) -> AbstractAsyncContextManager[httpx.AsyncClient]:
        settings = Settings(
            redis_url=TEST_REDIS_URL,
            database_url=TEST_DATABASE_URL,
            instance_id="test",
            **overrides,
        )
        return running_client(settings)

    return factory
