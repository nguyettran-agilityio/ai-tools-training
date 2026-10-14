# Standard library
from contextlib import asynccontextmanager

# Third-party
from fastapi import FastAPI

# Local application
# core
from app.core.config import get_settings
from app.core.error_handlers import register_exception_handlers
from app.core.logging_config import setup_logging
from app.core.middleware import register_middleware
from app.core.notifications import (
    CompositeNotifier,
    EmailNotifier,
    InMemoryEmailSender,
    SMTPEmailSender,
    WebSocketNotifier,
    set_notifier,
)
from app.core.ws_manager import get_connection_manager

# book
from app.modules.book.routers import router as book_router

# borrowing
from app.modules.borrowing.routers import router as borrowing_router

# category
from app.modules.category.routers import router as category_router

# reservation
from app.modules.reservation.routers import router as reservation_router
from app.modules.reservation.ws_routers import router as reservation_ws_router

# user
from app.modules.user.admin_routers import router as user_admin_router
from app.modules.user.routers import router as user_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.debug)
    # Schema is managed by Alembic migrations (`alembic upgrade head`), run
    # before starting the app — not auto-created here.
    # Switch from the default `InMemoryNotifier` to real delivery, fanned out
    # to both channels: WebSocket reaches whoever's online right now; email
    # is the durable channel that still reaches a member who isn't. Falls
    # back to `InMemoryEmailSender` when no SMTP host is configured, so
    # dev/test boot without real credentials. Tests re-bind the whole
    # notifier themselves (`test_reservation_notify.py` back to a plain
    # `InMemoryNotifier`, `test_websocket.py` to a bare `WebSocketNotifier`
    # on their own terms) since this runs on every `client` fixture too.
    email_sender = (
        SMTPEmailSender(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            from_address=settings.smtp_from_address,
            use_tls=settings.smtp_use_tls,
        )
        if settings.smtp_host
        else InMemoryEmailSender()
    )
    set_notifier(
        CompositeNotifier(
            [WebSocketNotifier(get_connection_manager()), EmailNotifier(email_sender)]
        )
    )
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    register_exception_handlers(app)
    register_middleware(app)
    app.include_router(user_router)
    app.include_router(user_admin_router)
    app.include_router(category_router)
    app.include_router(book_router)
    app.include_router(borrowing_router)
    app.include_router(reservation_router)
    app.include_router(reservation_ws_router)

    @app.get("/health", tags=["health"])
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
