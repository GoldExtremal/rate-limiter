import asyncio

import asyncpg
import httpx

from app.migrate import load_migrations, migrate, seed_client_limits
from tests.conftest import TEST_DATABASE_URL, ClientFactory


async def allowed_count(client: httpx.AsyncClient, client_id: str, attempts: int) -> int:
    payload = {"client_id": client_id}
    responses = [await client.post("/check", json=payload) for _ in range(attempts)]
    return sum(response.json()["allowed"] is True for response in responses)


async def test_migrations_are_applied_once(database: asyncpg.Connection) -> None:
    assert await migrate(TEST_DATABASE_URL, load_migrations()) == []


async def test_concurrent_migration_runs_do_not_conflict(database: asyncpg.Connection) -> None:
    await database.execute("DROP TABLE client_limits, schema_migrations")

    results = await asyncio.gather(
        *(migrate(TEST_DATABASE_URL, load_migrations()) for _ in range(3))
    )

    assert sorted(version for applied in results for version in applied) == ["0001_client_limits"]


async def test_seed_does_not_overwrite_manual_changes(database: asyncpg.Connection) -> None:
    await seed_client_limits(database, {"tenant": 5})
    await database.execute("UPDATE client_limits SET rate_limit = 7 WHERE client_id = 'tenant'")

    await seed_client_limits(database, {"tenant": 5, "other": 3})

    rows = await database.fetch("SELECT client_id, rate_limit FROM client_limits ORDER BY 1")
    assert [tuple(row) for row in rows] == [("other", 3), ("tenant", 7)]


async def test_individual_limits_from_postgres_are_applied(
    app_client: ClientFactory, database: asyncpg.Connection
) -> None:
    await seed_client_limits(database, {"vip": 5, "blocked": 0})

    async with app_client(rate_limit=2) as client:
        health = (await client.get("/health")).json()
        vip = await allowed_count(client, "vip", 7)
        blocked = await allowed_count(client, "blocked", 2)
        regular = await allowed_count(client, "regular", 4)

    assert health["limits_loaded"] is True
    assert health["limits_count"] == 2
    assert (vip, blocked, regular) == (5, 0, 2)
