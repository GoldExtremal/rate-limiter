import asyncio
import os

import httpx
from redis.asyncio import Redis

from app.limiter import key_for
from tests.acceptance.conftest import NGINX_URL

APP_REDIS_URL = os.environ.get("APP_REDIS_URL", "redis://localhost:6379/0")
SEEDED_CLIENT = "client-b"
SEEDED_LIMIT = 50


async def test_seeded_individual_limit_is_shared_by_instances() -> None:
    redis = Redis.from_url(APP_REDIS_URL)
    try:
        await redis.delete(key_for(SEEDED_CLIENT))
        async with httpx.AsyncClient(base_url=NGINX_URL, timeout=30) as client:
            responses = await asyncio.gather(
                *(client.post("/check", json={"client_id": SEEDED_CLIENT}) for _ in range(200))
            )
    finally:
        await redis.delete(key_for(SEEDED_CLIENT))
        await redis.aclose()

    assert sum(response.json()["allowed"] is True for response in responses) == SEEDED_LIMIT
    assert {response.headers["X-Instance-Id"] for response in responses} == {"app1", "app2"}
