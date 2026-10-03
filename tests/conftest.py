import os
from collections.abc import AsyncIterator

import httpx
import pytest
from asgi_lifespan import LifespanManager

from app.config import Settings
from app.instance import InstanceIdASGI
from app.main import create_app


def env_url(name: str, default: str) -> str:
    return os.environ.get(name, default)


@pytest.fixture
def test_redis_url() -> str:
    return env_url("TEST_REDIS_URL", "redis://localhost:6379/15")


def make_client(app: InstanceIdASGI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def running_client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = InstanceIdASGI(create_app(settings), settings.instance_id)
    async with LifespanManager(app), make_client(app) as client:
        yield client
