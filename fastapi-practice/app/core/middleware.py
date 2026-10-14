"""App-wide middleware: request id / request logging, CORS. Registered once
via `register_middleware(app)` from `main.py`'s app factory.
"""

# Standard library
import logging
import time
import uuid

# Third-party
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

# Local application
# core
from app.core.config import get_settings
from app.core.logging_config import request_id_var

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request id (incoming `X-Request-ID` header or a fresh uuid4),
    echoes it on the response, and logs one line per request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
            duration_ms = (time.perf_counter() - start) * 1000
            response.headers[REQUEST_ID_HEADER] = request_id
            logger.info(
                "%s %s -> %s (%.2fms)",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )
            return response
        finally:
            # Reset after logging, so the summary line above still carries
            # this request's id.
            request_id_var.reset(token)


def register_middleware(app: FastAPI) -> None:
    """Register all app-wide middleware. Call once from `main.py`'s app factory.
    Order matters: `CORSMiddleware` is added last so it ends up outermost."""
    settings = get_settings()

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        # Auth here is a bearer JWT (Authorization header), not a cookie, so
        # credentialed cross-origin requests are never needed. Keeping this
        # explicitly False also means browsers will always honor
        # `allow_origins=["*"]` in dev — pairing "*" with allow_credentials=True
        # is invalid per the CORS spec and browsers reject it outright.
        allow_credentials=False,
    )
