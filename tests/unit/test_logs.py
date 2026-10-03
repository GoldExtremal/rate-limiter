import json
import logging
import sys
from collections.abc import Iterator

import pytest

from app.logs import UVICORN_ACCESS_LOGGER, UVICORN_LOGGERS, JsonFormatter, configure_logging


def record(message: str, **extra: object) -> logging.LogRecord:
    entry = logging.makeLogRecord({"name": "app.test", "levelname": "WARNING", "msg": message})
    for key, value in extra.items():
        setattr(entry, key, value)
    return entry


def test_record_is_one_json_line_with_context() -> None:
    line = JsonFormatter("app1").format(record("redis is unavailable", kind="timeout"))

    entry = json.loads(line)
    assert "\n" not in line
    assert entry["level"] == "warning"
    assert entry["logger"] == "app.test"
    assert entry["instance"] == "app1"
    assert entry["message"] == "redis is unavailable"
    assert entry["kind"] == "timeout"
    assert entry["ts"].endswith("+00:00")


def test_exception_is_serialized() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        failed = logging.makeLogRecord({"msg": "failed", "exc_info": sys.exc_info()})

    entry = json.loads(JsonFormatter("app1").format(failed))

    assert "RuntimeError: boom" in entry["exception"]


@pytest.fixture
def isolated_logging() -> Iterator[None]:
    root = logging.getLogger()
    saved_root = (root.handlers[:], root.level)
    saved_uvicorn = {
        name: (logging.getLogger(name).handlers[:], logging.getLogger(name).propagate)
        for name in (*UVICORN_LOGGERS, UVICORN_ACCESS_LOGGER)
    }
    try:
        yield
    finally:
        root.handlers[:], level = saved_root
        root.setLevel(level)
        for name, (handlers, propagate) in saved_uvicorn.items():
            logging.getLogger(name).handlers[:] = handlers
            logging.getLogger(name).propagate = propagate


@pytest.mark.usefixtures("isolated_logging")
def test_uvicorn_logs_go_through_the_same_formatter(capsys: pytest.CaptureFixture[str]) -> None:
    uvicorn_logger = logging.getLogger("uvicorn.error")
    uvicorn_logger.addHandler(logging.StreamHandler())
    uvicorn_logger.propagate = False

    configure_logging("info", "json", "app2")
    uvicorn_logger.info("Application startup complete.")

    entry = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert entry["logger"] == "uvicorn.error"
    assert entry["instance"] == "app2"


@pytest.mark.usefixtures("isolated_logging")
def test_access_log_stays_disabled() -> None:
    configure_logging("info", "json", "app1")

    assert logging.getLogger(UVICORN_ACCESS_LOGGER).hasHandlers() is False


def test_uvicorn_color_message_is_not_duplicated() -> None:
    line = JsonFormatter("app1").format(record("Uvicorn running", color_message="\x1b[1m"))

    assert "color_message" not in json.loads(line)
