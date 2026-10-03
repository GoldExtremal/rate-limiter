import os

import httpx

NGINX_URL = os.environ.get("NGINX_URL", "http://localhost:8080")
APP_URLS = os.environ.get("APP_URLS", "http://localhost:8001,http://localhost:8002").split(",")


async def test_balancer_spreads_requests_over_both_instances() -> None:
    async with httpx.AsyncClient(base_url=NGINX_URL) as client:
        responses = [await client.get("/health") for _ in range(40)]

    assert all(response.status_code == 200 for response in responses)
    assert {response.headers["X-Instance-Id"] for response in responses} == {"app1", "app2"}


async def test_each_instance_is_reachable_directly() -> None:
    async with httpx.AsyncClient() as client:
        responses = [await client.get(f"{url}/health") for url in APP_URLS]

    instance_ids = [response.headers["X-Instance-Id"] for response in responses]
    assert instance_ids == ["app1", "app2"]
