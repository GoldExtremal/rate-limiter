from app.config import Settings
from tests.conftest import ClientFactory, running_client


async def test_app_starts_without_redis_and_postgres() -> None:
    settings = Settings(
        redis_url="redis://127.0.0.1:1/0",
        database_url="postgresql://nobody:nothing@127.0.0.1:1/none",
        instance_id="no-dependencies",
    )
    async with running_client(settings) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Instance-Id"] == "no-dependencies"
    assert response.json()["limits_loaded"] is False


async def test_app_starts_with_redis(app_client: ClientFactory) -> None:
    async with app_client() as client:
        response = await client.get("/health")

    assert response.status_code == 200
