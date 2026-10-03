import asyncio
import logging
from collections.abc import Mapping
from types import MappingProxyType

import asyncpg

logger = logging.getLogger(__name__)


class LimitsProvider:
    def __init__(self, default_limit: int, limits: Mapping[str, int] | None) -> None:
        self._default_limit = default_limit
        self._limits: Mapping[str, int] = MappingProxyType(dict(limits or {}))
        self.loaded = limits is not None

    def get(self, client_id: str) -> int:
        return self._limits.get(client_id, self._default_limit)

    @property
    def count(self) -> int:
        return len(self._limits)


async def fetch_limits(database_url: str) -> dict[str, int]:
    connection = await asyncpg.connect(database_url)
    try:
        rows = await connection.fetch("SELECT client_id, rate_limit FROM client_limits")
    finally:
        await connection.close()
    return {row["client_id"]: row["rate_limit"] for row in rows}


async def load_limits(database_url: str, timeout_sec: float) -> dict[str, int] | None:
    try:
        async with asyncio.timeout(timeout_sec):
            return await fetch_limits(database_url)
    except (OSError, TimeoutError, asyncpg.PostgresError, asyncpg.InterfaceError) as error:
        logger.warning("client limits are unavailable, using defaults: %s", type(error).__name__)
        return None
