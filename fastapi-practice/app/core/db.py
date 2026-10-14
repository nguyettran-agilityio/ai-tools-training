"""SQLModel engine + session dependency.

Schema creation/evolution is Alembic's job (`alembic upgrade head`), not
this module's — there is deliberately no `create_all()` helper here. Run
migrations before starting the app or any CLI script; see `alembic/` and
the README's "Database Migrations" section.
"""

# Standard library
from collections.abc import Generator
from contextlib import contextmanager

# Third-party
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

# Local application
# core
from app.core.config import get_settings

settings = get_settings()

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, echo=False, connect_args=connect_args)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    """Enforce SQLite foreign key constraints, which are off by default."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Context-manager twin of `get_session`, for non-FastAPI callers (CLI
    scripts, ...). Commits on success, rolls back on exception."""
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a DB session, overridable in tests.
    Delegates to `session_scope` for the same commit/rollback contract."""
    with session_scope() as session:
        yield session
