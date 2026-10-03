FROM ghcr.io/astral-sh/uv:0.12.22 AS uv

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./

FROM base AS runtime
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
RUN useradd --system --uid 10001 --no-create-home app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:build_asgi_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log", "--limit-concurrency", "2048"]
