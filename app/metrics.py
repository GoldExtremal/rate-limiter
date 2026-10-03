from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

from app.decision import Decision, DegradedReason

DURATION_BUCKETS = (0.00025, 0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)


def outcome_of(decision: Decision) -> str:
    if decision.degraded is DegradedReason.OVERLOADED:
        return "shed"
    prefix = "" if decision.degraded is None else "degraded_"
    return prefix + ("allowed" if decision.allowed else "rejected")


class Metrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.decisions = Counter(
            "ratelimit_decisions",
            "Rate limit decisions by outcome",
            ["outcome"],
            registry=self.registry,
        )
        self.check_duration = Histogram(
            "ratelimit_check_duration_seconds",
            "Full rate limit check duration, including admission wait",
            buckets=DURATION_BUCKETS,
            registry=self.registry,
        )
        self.redis_duration = Histogram(
            "ratelimit_redis_duration_seconds",
            "Duration of the Redis script call",
            buckets=DURATION_BUCKETS,
            registry=self.registry,
        )
        self.redis_errors = Counter(
            "ratelimit_redis_errors",
            "Redis unavailability errors by kind",
            ["kind"],
            registry=self.registry,
        )
        self.script_errors = Counter(
            "ratelimit_script_errors",
            "Redis errors that indicate a bug rather than unavailability",
            registry=self.registry,
        )
        self.breaker_state = Gauge(
            "ratelimit_circuit_breaker_state",
            "Circuit breaker state: 0 closed, 1 open, 2 half-open",
            registry=self.registry,
        )
        self.inflight_checks = Gauge(
            "ratelimit_inflight_checks",
            "Admission slots in use",
            registry=self.registry,
        )
        self.limits_loaded = Gauge(
            "ratelimit_limits_loaded",
            "1 if client limits were loaded from PostgreSQL",
            registry=self.registry,
        )

    def record(self, decision: Decision, duration_sec: float) -> None:
        self.decisions.labels(outcome_of(decision)).inc()
        self.check_duration.observe(duration_sec)
