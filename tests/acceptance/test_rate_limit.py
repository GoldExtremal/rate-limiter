import asyncio
from typing import Any

import httpx

from tests.acceptance.conftest import APP_URLS, DEFAULT_LIMIT, NGINX_URL, unique_client_id

PARALLEL_REQUESTS = 500


def parallel_client() -> httpx.AsyncClient:
    limits = httpx.Limits(max_connections=PARALLEL_REQUESTS, max_keepalive_connections=0)
    return httpx.AsyncClient(limits=limits, timeout=30)


async def post_check(client: httpx.AsyncClient, base_url: str, client_id: str) -> httpx.Response:
    return await client.post(f"{base_url}/check", json={"client_id": client_id})


def bodies_of(responses: list[httpx.Response]) -> list[dict[str, Any]]:
    assert all(response.status_code == 200 for response in responses)
    bodies: list[dict[str, Any]] = [response.json() for response in responses]
    assert all(body["remaining"] is not None for body in bodies)
    return bodies


def allowed_count(responses: list[httpx.Response]) -> int:
    return sum(body["allowed"] is True for body in bodies_of(responses))


async def test_500_parallel_requests_through_balancer_allow_exactly_100() -> None:
    client_id = unique_client_id("acceptance")
    async with parallel_client() as client:
        responses = await asyncio.gather(
            *(post_check(client, NGINX_URL, client_id) for _ in range(PARALLEL_REQUESTS))
        )

    assert allowed_count(responses) == DEFAULT_LIMIT
    assert {response.headers["X-Instance-Id"] for response in responses} == {"app1", "app2"}


async def test_500_parallel_requests_split_between_instances_allow_exactly_100() -> None:
    client_id = unique_client_id("direct")
    async with parallel_client() as client:
        responses = await asyncio.gather(
            *(
                post_check(client, APP_URLS[index % len(APP_URLS)], client_id)
                for index in range(PARALLEL_REQUESTS)
            )
        )

    assert allowed_count(responses) == DEFAULT_LIMIT


async def test_parallel_clients_do_not_affect_each_other() -> None:
    first, second = unique_client_id("first"), unique_client_id("second")
    async with parallel_client() as client:
        responses = await asyncio.gather(
            *(post_check(client, NGINX_URL, client_id) for client_id in [first, second] * 300)
        )

    assert allowed_count(responses[0::2]) == DEFAULT_LIMIT
    assert allowed_count(responses[1::2]) == DEFAULT_LIMIT


async def test_demo_limit_is_shared_by_instances() -> None:
    client_id = unique_client_id("demo")
    headers = {"X-Client-Id": client_id}
    async with httpx.AsyncClient(timeout=30) as client:
        responses = [
            await client.get(f"{APP_URLS[index % len(APP_URLS)]}/demo", headers=headers)
            for index in range(DEFAULT_LIMIT + 1)
        ]
        rejected = await client.get(f"{NGINX_URL}/demo", headers=headers)

    statuses = [response.status_code for response in responses]
    assert statuses == [200] * DEFAULT_LIMIT + [429]
    assert rejected.status_code == 429
    assert rejected.headers["X-RateLimit-Remaining"] == "0"
    assert int(rejected.headers["Retry-After"]) >= 1


async def test_each_demo_request_through_balancer_is_counted_once() -> None:
    headers = {"X-Client-Id": unique_client_id("once")}
    async with httpx.AsyncClient(base_url=NGINX_URL, timeout=30) as client:
        remaining = [
            int((await client.get("/demo", headers=headers)).headers["X-RateLimit-Remaining"])
            for _ in range(DEFAULT_LIMIT)
        ]

    assert remaining == list(range(DEFAULT_LIMIT - 1, -1, -1))
