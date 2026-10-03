import asyncio
import os
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import docker
import httpx
import pytest
from docker.models.containers import Container
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import Settings
from tests.conftest import TEST_REDIS_URL, running_client

COMPOSE_PROJECT = os.environ.get("CHAOS_COMPOSE_PROJECT", "rate-limiter")
APP_REDIS_URL = os.environ.get("APP_REDIS_URL", "redis://localhost:6379/0")
NGINX_URL = os.environ.get("NGINX_URL", "http://localhost:8080")
APP_URLS = os.environ.get("APP_URLS", "http://localhost:8001,http://localhost:8002").split(",")
UNREACHABLE_DATABASE = "postgresql://nobody:nothing@127.0.0.1:1/none"
DEFAULT_MAXMEMORY = "256mb"
COMPOSE_BREAKER_COOLDOWN_SEC = 5

InProcessFactory = Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]


def redis_container() -> Container:
    containers = docker.from_env().containers.list(
        all=True,
        filters={
            "label": [
                f"com.docker.compose.project={COMPOSE_PROJECT}",
                "com.docker.compose.service=redis",
            ]
        },
    )
    assert len(containers) == 1
    container: Container = containers[0]
    return container


async def wait_for_redis(timeout_sec: float = 30) -> None:
    deadline = time.monotonic() + timeout_sec
    while True:
        client = Redis.from_url(APP_REDIS_URL, socket_timeout=1, socket_connect_timeout=1)
        try:
            await client.ping()
            return
        except (RedisError, OSError):
            if time.monotonic() > deadline:
                raise
            await asyncio.sleep(0.5)
        finally:
            await client.aclose()


async def restore_redis(container: Container) -> None:
    container.reload()
    if container.status == "paused":
        container.unpause()
    elif container.status != "running":
        container.start()
    await wait_for_redis()
    client = Redis.from_url(APP_REDIS_URL)
    try:
        await client.config_set("maxmemory", DEFAULT_MAXMEMORY)
    finally:
        await client.aclose()


async def wait_until_compose_apps_recover(timeout_sec: float = 20) -> None:
    deadline = time.monotonic() + timeout_sec
    async with httpx.AsyncClient(timeout=5) as client:
        for url in APP_URLS:
            while True:
                body = (await client.post(f"{url}/check", json={"client_id": "probe"})).json()
                if body["degraded"] is None:
                    break
                assert time.monotonic() < deadline
                await asyncio.sleep(0.5)


@pytest.fixture
async def redis_chaos() -> AsyncIterator[Container]:
    container = redis_container()
    await restore_redis(container)
    try:
        yield container
    finally:
        await restore_redis(container)
        await wait_until_compose_apps_recover()


@pytest.fixture
def in_process_app() -> InProcessFactory:
    def factory(**overrides: Any) -> AbstractAsyncContextManager[httpx.AsyncClient]:
        defaults: dict[str, Any] = {
            "redis_url": TEST_REDIS_URL,
            "database_url": UNREACHABLE_DATABASE,
            "limits_query_timeout_ms": 200,
            "instance_id": "chaos",
            "breaker_cooldown_sec": 1,
        }
        return running_client(Settings(**(defaults | overrides)))

    return factory
