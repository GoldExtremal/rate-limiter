import pytest

from tests.conftest import ClientFactory

RATE_LIMIT_HEADERS = ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset")


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [(b"X-Client-Id", b"")],
        [(b"X-Client-Id", b"\xff\xfe")],
        [(b"X-Client-Id", b"x" * 257)],
    ],
)
async def test_invalid_client_id_is_rejected_with_400(
    app_client: ClientFactory, headers: list[tuple[bytes, bytes]]
) -> None:
    async with app_client() as client:
        response = await client.get("/demo", headers=headers)

    assert response.status_code == 400


async def test_allowed_request_reaches_handler_with_rate_limit_headers(
    app_client: ClientFactory,
) -> None:
    async with app_client(rate_limit=5) as client:
        response = await client.get("/demo", headers={"X-Client-Id": "demo-ok"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert [response.headers[name] for name in RATE_LIMIT_HEADERS[:2]] == ["5", "4"]
    assert int(response.headers["X-RateLimit-Reset"]) > 0
    assert "Retry-After" not in response.headers


async def test_exceeded_limit_returns_429_with_all_headers(app_client: ClientFactory) -> None:
    async with app_client(rate_limit=1, window_sec=2) as client:
        await client.get("/demo", headers={"X-Client-Id": "demo-limit"})
        response = await client.get("/demo", headers={"X-Client-Id": "demo-limit"})

    assert response.status_code == 429
    assert response.json() == {"detail": "rate limit exceeded"}
    assert response.headers["X-RateLimit-Limit"] == "1"
    assert response.headers["X-RateLimit-Remaining"] == "0"
    assert int(response.headers["X-RateLimit-Reset"]) > 0
    assert 1 <= int(response.headers["Retry-After"]) <= 3


async def test_utf8_header_and_json_body_share_one_counter(app_client: ClientFactory) -> None:
    client_id = "пользователь"
    async with app_client(rate_limit=2) as client:
        await client.post("/check", json={"client_id": client_id})
        response = await client.get("/demo", headers=[(b"X-Client-Id", client_id.encode())])

    assert response.headers["X-RateLimit-Remaining"] == "0"


async def test_unprotected_paths_are_not_limited(app_client: ClientFactory) -> None:
    async with app_client(rate_limit=0) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert not any(name in response.headers for name in RATE_LIMIT_HEADERS)
