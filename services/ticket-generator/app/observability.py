import logging
import time

from pythonjsonlogger.json import JsonFormatter

SERVICE = "ticket-generator"


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.service = SERVICE
        record.request_id = getattr(record, "request_id", "-")
        return True


def setup_logging(level: str) -> None:
    formatter = JsonFormatter(
        "%(asctime)s %(levelname)s %(service)s %(name)s %(message)s %(request_id)s",
        rename_fields={"asctime": "ts", "levelname": "level", "name": "logger", "message": "msg"},
    )
    formatter.converter = time.gmtime
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.addFilter(_ContextFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # it logs every request URL at INFO
