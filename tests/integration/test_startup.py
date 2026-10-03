from app.config import Settings
from tests.conftest import ClientFactory, running_client


async def test_app_starts_and_serves_health_without_redis() -> None:
    settings = Settings(redis_url="redis://127.0.0.1:1/0", instance_id="no-redis")
    async with running_client(settings) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Instance-Id"] == "no-redis"


async def test_app_starts_with_redis(app_client: ClientFactory) -> None:
    async with app_client() as client:
        response = await client.get("/health")

    assert response.status_code == 200
