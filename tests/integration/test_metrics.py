from prometheus_client.parser import text_string_to_metric_families
from redis.asyncio import Redis

from app.limiter import key_for
from tests.conftest import ClientFactory


def samples(text: str) -> dict[str, float]:
    values = {}
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            labels = ",".join(f"{k}={v}" for k, v in sorted(sample.labels.items()))
            values[f"{sample.name}{{{labels}}}"] = sample.value
    return values


async def test_metrics_count_decisions_and_errors(app_client: ClientFactory, redis: Redis) -> None:
    await redis.set(key_for("broken"), "not-a-sorted-set")
    async with app_client(rate_limit=2) as client:
        for _ in range(3):
            await client.post("/check", json={"client_id": "metered"})
        await client.post("/check", json={"client_id": "broken"})
        response = await client.get("/metrics")

    values = samples(response.text)
    assert response.status_code == 200
    assert values["ratelimit_decisions_total{outcome=allowed}"] == 2
    assert values["ratelimit_decisions_total{outcome=rejected}"] == 1
    assert values["ratelimit_script_errors_total{}"] == 1
    assert values["ratelimit_check_duration_seconds_count{}"] == 3
    assert values["ratelimit_circuit_breaker_state{}"] == 0
    assert values["ratelimit_limits_loaded{}"] == 1


async def test_metrics_count_redis_unavailability(app_client: ClientFactory) -> None:
    async with app_client(redis_url="redis://127.0.0.1:1/0", breaker_failure_threshold=2) as client:
        for _ in range(4):
            await client.post("/check", json={"client_id": "metered"})
        values = samples((await client.get("/metrics")).text)

    assert values["ratelimit_redis_errors_total{kind=connection}"] == 2
    assert values["ratelimit_decisions_total{outcome=degraded_allowed}"] == 4
    assert values["ratelimit_circuit_breaker_state{}"] == 1
