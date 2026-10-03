import os
import random
import re
from collections import Counter

import requests
from locust import FastHttpUser, constant_throughput, events, task
from locust.env import Environment
from locust.runners import WorkerRunner

REGULAR_CLIENTS = [f"load-{index}" for index in range(10_000)]
HOT_CLIENT = "load-hot"
USER_RPS = float(os.environ.get("LOAD_USER_RPS", "10"))
APP_METRICS_URLS = os.environ.get(
    "LOAD_APP_METRICS_URLS", "http://app1:8000/metrics,http://app2:8000/metrics"
).split(",")
REPORT_PATH = os.environ.get("LOAD_APP_REPORT", "/mnt/locust/reports/app-metrics.txt")
SAMPLE = re.compile(r'^(ratelimit_\w+?)(?:\{\w+="(\w+)"\})? ([0-9.e+-]+)$', re.MULTILINE)


def scrape_app_metrics() -> Counter[str]:
    totals: Counter[str] = Counter()
    for url in APP_METRICS_URLS:
        text = requests.get(url, timeout=5).text
        for name, label, value in SAMPLE.findall(text):
            totals[f"{name}:{label}" if label else name] += float(value)
    return totals


def labelled(delta: Counter[str], metric: str) -> dict[str, int]:
    prefix = f"{metric}:"
    return {
        key.removeprefix(prefix): int(value)
        for key, value in sorted(delta.items())
        if key.startswith(prefix)
    }


def mean_ms(delta: Counter[str], histogram: str) -> float:
    count = delta[f"{histogram}_count"]
    return 1000 * delta[f"{histogram}_sum"] / count if count else 0.0


class LimiterClient(FastHttpUser):
    wait_time = constant_throughput(USER_RPS)

    @task(9)
    def regular_client(self) -> None:
        self.client.post(
            "/check", json={"client_id": random.choice(REGULAR_CLIENTS)}, name="/check regular"
        )

    @task(1)
    def hot_client(self) -> None:
        self.client.post("/check", json={"client_id": HOT_CLIENT}, name="/check hot")


@events.test_start.add_listener
def remember_app_metrics(environment: Environment, **_: object) -> None:
    if not isinstance(environment.runner, WorkerRunner):
        environment.app_metrics_before = scrape_app_metrics()


@events.test_stop.add_listener
def report_app_metrics(environment: Environment, **_: object) -> None:
    if isinstance(environment.runner, WorkerRunner):
        return
    delta = scrape_app_metrics() - environment.app_metrics_before
    outcomes = labelled(delta, "ratelimit_decisions_total")
    redis_errors = labelled(delta, "ratelimit_redis_errors_total")
    degraded = sum(v for k, v in outcomes.items() if k.startswith(("degraded", "shed")))
    lines = [
        f"decisions: {outcomes}",
        f"degraded or shed: {degraded}",
        f"mean check duration, ms: {mean_ms(delta, 'ratelimit_check_duration_seconds'):.3f}",
        f"mean redis call duration, ms: {mean_ms(delta, 'ratelimit_redis_duration_seconds'):.3f}",
        f"redis errors: {redis_errors}",
    ]
    report = "\n".join(lines)
    print(report)
    with open(REPORT_PATH, "w") as file:
        file.write(report + "\n")
