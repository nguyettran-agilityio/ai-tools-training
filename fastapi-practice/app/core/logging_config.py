"""Application logging setup.

The root logger and uvicorn's loggers share one handler that injects the
current request id (from a `ContextVar` set by `RequestContextMiddleware`)
into every log record.
"""

# Standard library
import contextvars
import logging

# Set by RequestContextMiddleware for the lifetime of a request; read by
# RequestIdFilter on every log record. Default "-" covers log lines emitted
# outside a request (startup, background tasks, etc.).
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | request_id=%(request_id)s | %(message)s"

# Uvicorn's own loggers are configured before our lifespan runs (uvicorn
# applies its default log config at startup) and default to propagate=False,
# so they need their handler set explicitly to line up with ours.
_UVICORN_LOGGER_NAMES = ("uvicorn", "uvicorn.error", "uvicorn.access")


class RequestIdFilter(logging.Filter):
    """Injects the current request id (from `request_id_var`) into every log record
    that passes through a handler this filter is attached to."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def setup_logging(debug: bool = False) -> None:
    """Configure the root + uvicorn loggers with one shared, request-id-aware
    handler. Call once, from `main.py`'s app factory."""
    level = logging.DEBUG if debug else logging.INFO

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    handler.addFilter(RequestIdFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers = [handler]

    for name in _UVICORN_LOGGER_NAMES:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = [handler]
        uvicorn_logger.propagate = False
        uvicorn_logger.setLevel(level)
