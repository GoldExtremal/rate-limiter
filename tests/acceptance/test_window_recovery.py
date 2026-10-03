import asyncio

import httpx
import pytest

from tests.acceptance.conftest import DEFAULT_LIMIT, NGINX_URL, unique_client_id

WINDOW_SEC = 60
SAFETY_MARGIN_SEC = 1.5


async def allowed_in_burst(client: httpx.AsyncClient, client_id: str, count: int) -> int:
    responses = await asyncio.gather(
        *(client.post("/check", json={"client_id": client_id}) for _ in range(count))
    )
    return sum(response.json()["allowed"] is True for response in responses)


@pytest.mark.slow
async def test_limit_recovers_after_window_on_running_instances() -> None:
    client_id = unique_client_id("recovery")
    async with httpx.AsyncClient(base_url=NGINX_URL, timeout=30) as client:
        exhausted = await allowed_in_burst(client, client_id, DEFAULT_LIMIT + 20)
        await asyncio.sleep(WINDOW_SEC + SAFETY_MARGIN_SEC)
        recovered = await allowed_in_burst(client, client_id, DEFAULT_LIMIT + 20)

    assert exhausted == DEFAULT_LIMIT
    assert recovered == DEFAULT_LIMIT
