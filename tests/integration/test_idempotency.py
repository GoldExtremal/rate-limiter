import asyncio

from tests.conftest import ClientFactory


async def test_retry_with_same_request_id_is_not_counted_twice(app_client: ClientFactory) -> None:
    async with app_client(rate_limit=2) as client:
        first = await client.post("/check", json={"client_id": "retry", "request_id": "r-1"})
        retry = await client.post("/check", json={"client_id": "retry", "request_id": "r-1"})
        other = await client.post("/check", json={"client_id": "retry", "request_id": "r-2"})
        over = await client.post("/check", json={"client_id": "retry", "request_id": "r-3"})

    assert [first.json()["allowed"], retry.json()["allowed"]] == [True, True]
    assert [first.json()["remaining"], retry.json()["remaining"]] == [1, 1]
    assert other.json() | {"reset_at": None} == {
        "allowed": True,
        "remaining": 0,
        "reset_at": None,
        "degraded": None,
    }
    assert over.json()["allowed"] is False


async def test_retry_of_rejected_request_is_still_rejected(app_client: ClientFactory) -> None:
    async with app_client(rate_limit=1) as client:
        await client.post("/check", json={"client_id": "full", "request_id": "a"})
        rejected = await client.post("/check", json={"client_id": "full", "request_id": "b"})
        retried = await client.post("/check", json={"client_id": "full", "request_id": "b"})

    assert rejected.json()["allowed"] is False
    assert retried.json()["allowed"] is False


async def test_request_id_is_counted_again_after_window(app_client: ClientFactory) -> None:
    async with app_client(rate_limit=1, window_sec=1) as client:
        await client.post("/check", json={"client_id": "late", "request_id": "x"})
        await asyncio.sleep(1.2)
        await client.post("/check", json={"client_id": "late", "request_id": "x"})
        other = await client.post("/check", json={"client_id": "late", "request_id": "y"})

    assert other.json()["allowed"] is False


async def test_demo_honours_request_id_header(app_client: ClientFactory) -> None:
    headers = {"X-Client-Id": "demo-retry", "X-Request-Id": "same"}
    async with app_client(rate_limit=1) as client:
        responses = [await client.get("/demo", headers=headers) for _ in range(3)]
        invalid = await client.get(
            "/demo", headers={"X-Client-Id": "demo-retry", "X-Request-Id": "x" * 129}
        )

    assert [response.status_code for response in responses] == [200, 200, 200]
    assert invalid.status_code == 400


async def test_request_id_length_is_validated(app_client: ClientFactory) -> None:
    async with app_client() as client:
        response = await client.post("/check", json={"client_id": "c", "request_id": "x" * 129})

    assert response.status_code == 422
