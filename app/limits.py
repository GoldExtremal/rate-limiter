import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from types import MappingProxyType

import asyncpg

logger = logging.getLogger(__name__)

LimitsLoader = Callable[[], Awaitable[dict[str, int] | None]]


class LimitsProvider:
    def __init__(
        self,
        default_limit: int,
        limits: Mapping[str, int] | None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._default_limit = default_limit
        self._clock = clock
        self._limits: Mapping[str, int] = MappingProxyType({})
        self._loaded_at: float | None = None
        if limits is not None:
            self.replace(limits)

    @property
    def loaded(self) -> bool:
        return self._loaded_at is not None

    @property
    def count(self) -> int:
        return len(self._limits)

    def get(self, client_id: str) -> int:
        return self._limits.get(client_id, self._default_limit)

    def replace(self, limits: Mapping[str, int]) -> None:
        self._limits = MappingProxyType(dict(limits))
        self._loaded_at = self._clock()

    def snapshot_age_sec(self) -> float | None:
        return None if self._loaded_at is None else self._clock() - self._loaded_at


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
        logger.warning("client limits are unavailable: %s", type(error).__name__)
        return None


async def refresh_limits_forever(
    provider: LimitsProvider,
    load: LimitsLoader,
    interval_sec: float,
    on_failure: Callable[[], None],
) -> None:
    while True:
        await asyncio.sleep(interval_sec)
        limits = await load()
        if limits is None:
            on_failure()
        else:
            provider.replace(limits)
