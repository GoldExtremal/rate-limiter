import asyncio

import pytest

from app.limits import LimitsProvider, refresh_limits_forever
from tests.unit.fakes import FakeClock


def test_unknown_clients_get_default_limit() -> None:
    provider = LimitsProvider(100, {"vip": 500})

    assert (provider.get("vip"), provider.get("anyone")) == (500, 100)


def test_snapshot_is_not_affected_by_source_mapping() -> None:
    source = {"vip": 500}
    provider = LimitsProvider(100, source)
    source["vip"] = 1

    assert provider.get("vip") == 500


def test_snapshot_age_is_tracked() -> None:
    clock = FakeClock()
    provider = LimitsProvider(100, None, clock=clock)
    assert provider.snapshot_age_sec() is None
    provider.replace({"vip": 5})
    clock.advance(7)

    assert provider.loaded is True
    assert provider.snapshot_age_sec() == 7


async def test_refresh_replaces_snapshot_and_keeps_it_on_failure() -> None:
    provider = LimitsProvider(100, {"vip": 5})
    results: list[dict[str, int] | None] = [{"vip": 7}, None]
    failures: list[int] = []

    async def load() -> dict[str, int] | None:
        return results.pop(0) if results else None

    refresh = asyncio.create_task(
        refresh_limits_forever(provider, load, 0.01, lambda: failures.append(1))
    )
    await asyncio.sleep(0.05)
    refresh.cancel()
    with pytest.raises(asyncio.CancelledError):
        await refresh

    assert provider.get("vip") == 7
    assert len(failures) >= 1
