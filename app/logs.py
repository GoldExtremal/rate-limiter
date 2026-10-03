import json
import logging
from datetime import UTC, datetime
from typing import Literal

LogFormat = Literal["json", "text"]
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error")
UVICORN_ACCESS_LOGGER = "uvicorn.access"
STANDARD_RECORD_FIELDS = frozenset(vars(logging.makeLogRecord({}))) | {
    "message",
    "asctime",
    "color_message",
}


class JsonFormatter(logging.Formatter):
    def __init__(self, instance_id: str) -> None:
        super().__init__()
        self.instance_id = instance_id

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "instance": self.instance_id,
            "message": record.getMessage(),
        }
        entry.update(
            (key, value)
            for key, value in vars(record).items()
            if key not in STANDARD_RECORD_FIELDS and not key.startswith("_")
        )
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def text_formatter(instance_id: str) -> logging.Formatter:
    return logging.Formatter(
        f"%(asctime)s %(levelname)s instance={instance_id} %(name)s %(message)s"
    )


def configure_logging(level: str, log_format: LogFormat, instance_id: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter(instance_id) if log_format == "json" else text_formatter(instance_id)
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for name in UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    access_logger = logging.getLogger(UVICORN_ACCESS_LOGGER)
    access_logger.handlers.clear()
    access_logger.propagate = False
