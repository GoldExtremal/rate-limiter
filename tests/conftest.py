import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from redis.asyncio import Redis

from app.config import Settings
from app.instance import InstanceIdASGI
from app.main import create_app

TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")

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


@pytest.fixture
def app_client(redis: Redis) -> ClientFactory:
    def factory(**overrides: Any) -> AbstractAsyncContextManager[httpx.AsyncClient]:
        settings = Settings(redis_url=TEST_REDIS_URL, instance_id="test", **overrides)
        return running_client(settings)

    return factory
