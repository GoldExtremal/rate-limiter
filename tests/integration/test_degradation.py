import pytest
from redis.asyncio import Redis

from app.limiter import key_for
from tests.conftest import ClientFactory

UNREACHABLE_REDIS = "redis://127.0.0.1:1/0"


async def test_fail_open_allows_without_limit_state(app_client: ClientFactory) -> None:
    async with app_client(redis_url=UNREACHABLE_REDIS, fail_mode_open=True) as client:
        check = await client.post("/check", json={"client_id": "open"})
        demo = await client.get("/demo", headers={"X-Client-Id": "open"})

    assert check.status_code == 200
    assert check.json() == {
        "allowed": True,
        "remaining": None,
        "reset_at": None,
        "degraded": "redis_unavailable",
    }
    assert demo.status_code == 200
    assert demo.headers["X-RateLimit-Degraded"] == "redis_unavailable"
    assert "X-RateLimit-Remaining" not in demo.headers


async def test_fail_closed_rejects_without_429(app_client: ClientFactory) -> None:
    async with app_client(redis_url=UNREACHABLE_REDIS, fail_mode_open=False) as client:
        check = await client.post("/check", json={"client_id": "closed"})
        demo = await client.get("/demo", headers={"X-Client-Id": "closed"})

    assert check.status_code == 200
    assert check.json()["allowed"] is False
    assert check.json()["degraded"] == "redis_unavailable"
    assert demo.status_code == 503
    assert demo.headers["X-RateLimit-Degraded"] == "redis_unavailable"


@pytest.mark.parametrize("fail_mode_open", [True, False])
async def test_script_error_is_not_masked_as_unavailability(
    app_client: ClientFactory, redis: Redis, fail_mode_open: bool
) -> None:
    await redis.set(key_for("broken"), "not-a-sorted-set")

    async with app_client(fail_mode_open=fail_mode_open) as client:
        response = await client.post("/check", json={"client_id": "broken"})

    assert response.status_code == 500
