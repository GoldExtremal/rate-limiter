import os
from collections import Counter

from locust import LoadTestShape
from locustfile import USER_RPS, LimiterClient, labelled, mean_ms, scrape_app_metrics

STEP_USERS = int(os.environ.get("LOAD_STEP_USERS", "100"))
STEP_SEC = int(os.environ.get("LOAD_STEP_SEC", "15"))
MAX_USERS = int(os.environ.get("LOAD_MAX_USERS", "500"))
REPORT_PATH = os.environ.get("LOAD_SATURATION_REPORT", "/mnt/locust/reports/saturation.txt")

__all__ = ["LimiterClient", "SteppedLoad"]


class SteppedLoad(LoadTestShape):
    def __init__(self) -> None:
        super().__init__()
        self.current_step = -1
        self.step_metrics: Counter[str] = Counter()
        self.lines: list[str] = []

    def tick(self) -> tuple[int, float] | None:
        step = int(self.get_run_time() // STEP_SEC)
        if step != self.current_step:
            self.finish_step()
            self.current_step = step
        users = (step + 1) * STEP_USERS
        if users > MAX_USERS:
            self.write_report()
            return None
        return users, STEP_USERS

    def finish_step(self) -> None:
        metrics = scrape_app_metrics()
        if self.current_step >= 0:
            delta = metrics - self.step_metrics
            outcomes = labelled(delta, "ratelimit_decisions_total")
            stats = self.runner.stats.total
            users = (self.current_step + 1) * STEP_USERS
            p95 = stats.get_current_response_time_percentile(0.95) or 0
            self.lines.append(
                f"users={users} target_rps={users * USER_RPS:.0f} "
                f"rps={stats.current_rps:.0f} p95_ms={p95:.0f} "
                f"shed={outcomes.get('shed', 0)} "
                f"degraded={sum(v for k, v in outcomes.items() if k.startswith('degraded'))} "
                f"check_ms={mean_ms(delta, 'ratelimit_check_duration_seconds'):.1f} "
                f"redis_ms={mean_ms(delta, 'ratelimit_redis_duration_seconds'):.1f}"
            )
            print(self.lines[-1])
        self.step_metrics = metrics

    def write_report(self) -> None:
        with open(REPORT_PATH, "w") as file:
            file.write("\n".join(self.lines) + "\n")
