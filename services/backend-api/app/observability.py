import contextvars
import logging
import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram
from prometheus_fastapi_instrumentator import Instrumentator
from pythonjsonlogger.json import JsonFormatter

SERVICE = "backend-api"
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
log = logging.getLogger(__name__)


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.service = SERVICE
        record.request_id = request_id_var.get()
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
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True


def instrument(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id(request: Request, call_next):
        rid = request.headers.get("x-request-id", "")
        token = request_id_var.set(rid if _VALID_ID.match(rid) else str(uuid.uuid4()))
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse({"detail": "validation_error"}, status_code=422)

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse({"detail": "internal_error"}, status_code=500)

    Instrumentator().instrument(app).expose(app, include_in_schema=False)


PREDICTIONS = Counter(
    "triageiq_predictions", "Non-smoke predictions stored", ["model_version", "label"]
)
MODEL_CALL_SECONDS = Histogram(
    "triageiq_model_call_seconds",
    "Duration of calls to model-service",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
MODEL_CALL_ERRORS = Counter(
    "triageiq_model_call_errors", "Failed calls to model-service", ["reason"]
)
