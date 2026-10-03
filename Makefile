COMPOSE ?= docker compose
TEST_RUN = $(COMPOSE) --profile test run --rm tests
CHAOS_RUN = $(COMPOSE) --profile test run --rm chaos
LOAD_COMPOSE = $(COMPOSE) -f docker-compose.yml -f compose.load.yml
ACCEPTANCE_RUNS ?= 10
LOAD_STATS_DELAY ?= 90

.PHONY: up down test-image lint typecheck test-unit test-integration test-acceptance test-acceptance-repeat test-chaos test check load-up load load-saturation monitoring lint-monitoring audit

up:
	$(COMPOSE) up -d --build --wait

down:
	$(COMPOSE) --profile test --profile load down -v --remove-orphans

test-image:
	$(COMPOSE) --profile test build tests chaos

lint: test-image
	$(TEST_RUN) sh -c "ruff check . && ruff format --check ."

lint-monitoring:
	docker run --rm -v "$(CURDIR)/monitoring:/monitoring:ro" --entrypoint promtool prom/prometheus:v3.15.0 \
		check rules /monitoring/alerts.yml

typecheck: test-image
	$(TEST_RUN) mypy

test-unit: test-image
	$(TEST_RUN) pytest tests/unit

test-integration: test-image up
	$(TEST_RUN) pytest tests/integration

test-acceptance: test-image up
	$(TEST_RUN) pytest tests/acceptance -m "not slow"

test-acceptance-repeat: test-image up
	for run in $$(seq $(ACCEPTANCE_RUNS)); do $(TEST_RUN) pytest -q tests/acceptance -m "not slow" || exit 1; done

test-chaos: test-image up
	$(CHAOS_RUN) pytest tests/chaos

test: test-image up
	$(TEST_RUN) pytest --cov --cov-report=term tests/unit tests/integration tests/acceptance
	$(CHAOS_RUN) pytest tests/chaos

check: lint lint-monitoring typecheck test

load-up:
	$(LOAD_COMPOSE) up -d --build --wait

load: load-up
	mkdir -p load/reports
	$(LOAD_COMPOSE) --profile load run --rm locust & \
	sleep $(LOAD_STATS_DELAY); \
	docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" | grep -E "NAME|rate-limiter" > load/reports/docker-stats.txt; \
	wait
	cat load/reports/docker-stats.txt load/reports/app-metrics.txt

load-saturation: load-up
	mkdir -p load/reports
	$(LOAD_COMPOSE) --profile load run --rm locust -f saturation.py --headless --host=http://nginx \
		--processes=4 --csv=reports/saturation --only-summary
	cat load/reports/saturation.txt

monitoring:
	$(COMPOSE) --profile monitoring up -d --build --wait

audit: test-image
	$(TEST_RUN) sh -c "uv export --frozen --no-hashes --no-emit-project --format requirements-txt \
		> /tmp/requirements.txt && pip-audit --strict --no-deps --disable-pip -r /tmp/requirements.txt"
	$(COMPOSE) build app1
	docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:0.65.0 image \
		--quiet --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 rate-limiter-app1
