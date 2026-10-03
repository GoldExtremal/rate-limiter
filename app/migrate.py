import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import asyncpg
from pydantic import Field, NonNegativeInt
from pydantic_settings import BaseSettings, SettingsConfigDict

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
MIGRATION_LOCK_ID = 7_340_001

logger = logging.getLogger(__name__)


class MigrationSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "postgresql://ratelimiter:local-dev-only@postgres:5432/ratelimiter"
    seed_client_limits: dict[str, NonNegativeInt] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Migration:
    version: str
    sql: str


def load_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    return [
        Migration(version=path.stem, sql=path.read_text())
        for path in sorted(directory.glob("*.sql"))
    ]


async def applied_versions(connection: asyncpg.Connection) -> set[str]:
    await connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    rows = await connection.fetch("SELECT version FROM schema_migrations")
    return {row["version"] for row in rows}


async def apply_migrations(
    connection: asyncpg.Connection, migrations: list[Migration]
) -> list[str]:
    applied = await applied_versions(connection)
    newly_applied = []
    for migration in migrations:
        if migration.version in applied:
            continue
        async with connection.transaction():
            await connection.execute(migration.sql)
            await connection.execute(
                "INSERT INTO schema_migrations (version) VALUES ($1)", migration.version
            )
        newly_applied.append(migration.version)
    return newly_applied


async def seed_client_limits(connection: asyncpg.Connection, limits: Mapping[str, int]) -> None:
    await connection.executemany(
        "INSERT INTO client_limits (client_id, rate_limit) VALUES ($1, $2) "
        "ON CONFLICT (client_id) DO NOTHING",
        list(limits.items()),
    )


async def migrate(
    database_url: str, migrations: list[Migration], seed: Mapping[str, int] | None = None
) -> list[str]:
    connection = await asyncpg.connect(database_url)
    try:
        await connection.execute("SELECT pg_advisory_lock($1)", MIGRATION_LOCK_ID)
        try:
            applied = await apply_migrations(connection, migrations)
            if seed:
                await seed_client_limits(connection, seed)
            return applied
        finally:
            await connection.execute("SELECT pg_advisory_unlock($1)", MIGRATION_LOCK_ID)
    finally:
        await connection.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = MigrationSettings()
    applied = asyncio.run(
        migrate(settings.database_url, load_migrations(), settings.seed_client_limits)
    )
    logger.info("migrations applied: %s", ", ".join(applied) or "none")


if __name__ == "__main__":
    main()
