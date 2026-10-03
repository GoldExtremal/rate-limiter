from collections.abc import Iterator
from contextlib import contextmanager

import httpx
from fastapi import FastAPI

from app.decision import Decision, DegradedReason
from app.instance import InstanceIdASGI
from app.middleware import RateLimitMiddleware
from tests.conftest import make_client

ALLOWED = Decision(allowed=True, limit=10, remaining=9, reset_at=1_700_000_000, retry_after=None)
REJECTED = Decision(allowed=False, limit=10, remaining=0, reset_at=1_700_000_000, retry_after=7)
FAIL_OPEN = Decision(True, None, None, None, None, DegradedReason.REDIS_UNAVAILABLE)
FAIL_CLOSED = Decision(False, None, None, None, 4, DegradedReason.REDIS_UNAVAILABLE)
OVERLOADED = Decision(False, None, None, None, 1, DegradedReason.OVERLOADED)


class FakeLimiter:
    def __init__(self, decision: Decision) -> None:
        self.decision = decision
        self.checked: list[str] = []

    async def check(self, client_id: str) -> Decision:
        self.checked.append(client_id)
        return self.decision


@contextmanager
def demo_client(decision: Decision) -> Iterator[tuple[httpx.AsyncClient, FakeLimiter, list[int]]]:
    handled: list[int] = []
    app = FastAPI()
    app.state.limiter = FakeLimiter(decision)
    app.add_middleware(RateLimitMiddleware, protected_paths=["/demo"])

    @app.get("/demo")
    async def demo() -> dict[str, str]:
        handled.append(1)
        return {"status": "ok"}

    @app.get("/open")
    async def open_endpoint() -> dict[str, str]:
        return {"status": "ok"}

    yield make_client(InstanceIdASGI(app, "unit")), app.state.limiter, handled


async def get_demo(client: httpx.AsyncClient) -> httpx.Response:
    async with client:
        return await client.get("/demo", headers={"X-Client-Id": "client"})


async def test_allowed_request_reaches_handler_with_headers() -> None:
    with demo_client(ALLOWED) as (client, _, handled):
        response = await get_demo(client)

    assert response.status_code == 200
    assert handled == [1]
    assert response.headers["X-RateLimit-Limit"] == "10"
    assert response.headers["X-RateLimit-Remaining"] == "9"
    assert response.headers["X-RateLimit-Reset"] == "1700000000"


async def test_rejected_request_gets_429_without_handler() -> None:
    with demo_client(REJECTED) as (client, _, handled):
        response = await get_demo(client)

    assert response.status_code == 429
    assert handled == []
    assert response.headers["Retry-After"] == "7"
    assert response.headers["X-RateLimit-Remaining"] == "0"


async def test_fail_open_reaches_handler_without_limit_headers() -> None:
    with demo_client(FAIL_OPEN) as (client, _, handled):
        response = await get_demo(client)

    assert response.status_code == 200
    assert handled == [1]
    assert response.headers["X-RateLimit-Degraded"] == "redis_unavailable"
    assert not {"X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"} & set(
        response.headers
    )


async def test_fail_closed_returns_503_not_429() -> None:
    with demo_client(FAIL_CLOSED) as (client, _, handled):
        response = await get_demo(client)

    assert response.status_code == 503
    assert handled == []
    assert response.headers["Retry-After"] == "4"
    assert response.headers["X-RateLimit-Degraded"] == "redis_unavailable"


async def test_overload_returns_503_with_retry_after() -> None:
    with demo_client(OVERLOADED) as (client, _, _handled):
        response = await get_demo(client)

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert response.headers["X-RateLimit-Degraded"] == "overloaded"


async def test_unprotected_path_and_invalid_header_skip_limiter() -> None:
    with demo_client(REJECTED) as (client, limiter, _handled):
        async with client:
            unprotected = await client.get("/open")
            invalid = await client.get("/demo", headers=[(b"X-Client-Id", b"\xff")])

    assert unprotected.status_code == 200
    assert invalid.status_code == 400
    assert limiter.checked == []
