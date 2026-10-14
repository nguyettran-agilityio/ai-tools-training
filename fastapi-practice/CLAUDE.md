# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Fully implemented, not a skeleton. All 5 domain modules (`book`, `borrowing`,
`category`, `reservation`, `user`) have real models, endpoints, and business
logic: book/category CRUD, JWT auth (register/login/logout with a token
denylist), borrowing with a borrow limit and overdue tracking, a FIFO
reservation queue, WebSocket + email notifications, and rate-limited auth
endpoints. When extending a module, match the existing layering/patterns
(see Architecture below) rather than inventing a different shape.

As of this writing, rate limiting (`core/rate_limiter.py`) and the
per-module `TypedDict` for `update()` (see Architecture) live on their own
feature branches, not yet merged into `fastapi-practice-1` — if a fresh
checkout of that branch is missing either, that's why; check `git branch -a`.

## Commands

```bash
cd fastapi/practice
uv sync                              # install deps (creates .venv)
uv run alembic upgrade head          # apply migrations (creates library.db) — required before
                                      # first run and after pulling any new migration file
uv run fastapi dev                   # run dev server
uv run pytest                                        # run all tests
uv run pytest tests/modules/book/test_routers.py     # run a single test file
uv run pytest tests/modules/book/test_routers.py::TestCreateBook  # single test class
uv run pytest tests/modules/book/                    # every test for one module
uv run ruff check .                  # lint
uv run ruff format .                 # format
uv run mypy                          # type-check app/ (protects the repository-pattern
                                      # contract: an Interface's declared return type is
                                      # actually honored by every concrete implementation,
                                      # and update()'s TypedDict catches a wrong field name)
uv run pre-commit run --all-files    # ruff-check --fix + ruff-format + hygiene hooks
```

`curl http://127.0.0.1:8000/health` is the smoke check once the server is
running. `uv run python -m app.cli.seed_admin` creates the first admin
(there's no API route that produces one — `/auth/register` always creates a
`member`). `uv run python -m app.cli.seed_demo --force` seeds a small fixed
demo dataset. See README.md for the full endpoint list and getting-started steps.

## Architecture

Layered / clean architecture with the repository pattern, applied
per-module. Each domain lives entirely under `app/modules/<name>/` with the
same 7-file layout (`category/` is the canonical example; `user/` adds
`admin_routers.py` + `enums.py`, `reservation/` adds `ws_routers.py` + `enums.py`):

```
models.py               # SQLModel table(s)
schemas.py               # Pydantic request/response DTOs
mappers.py                 # model -> schema (DTO) mapping
repositories.py              # ABC interface extending core's CrudRepositoryInterface,
                              #   + a per-module TypedDict for update()'s field set
repositories_sqlmodel.py       # concrete implementation — the ONLY file in the module
                                #   allowed to import the SQLModel table or `sqlmodel` itself
services.py                      # business logic — no fastapi import, raises AppError subclasses
routers.py                         # FastAPI endpoints — depend on services, never repositories
```

Dependency direction is strict: **routers → services → repositories →
models**. Routers must not call repositories directly, and services must
depend on the repository _interface_, not the concrete SQLModel class.

**The repository pattern itself** (`app/core/repository_interface.py` +
`repository_sqlmodel.py`) is composition-based, not inheritance-based:
- `CrudBackend[ModelT, ReadT, UpdateT]` is the ORM-specific collaborator
  (one implementation per ORM/store — `SQLModelBackend` is the only one
  wired into the running app; a second one, `PeeweeBackend`, exists on the
  separate `feat/peewee-book-repository` branch purely as a swappability demo,
  deliberately not merged).
- `CrudRepositoryInterface[ReadT, UpdateT]` is what every
  `<Module>RepositoryInterface` inherits directly — it holds a `backend`
  (injected via the constructor) and forwards the 5 generic CRUD methods to
  it. A module's `repositories.py` only adds its own custom queries on top,
  reaching into `self.backend.session` for those (an accepted, documented
  leak — custom queries always need to know the underlying ORM).
- `UpdateT` is a per-module `TypedDict` (e.g. `BookUpdateFields`) declaring
  every field `update()` may ever be asked to change — including
  service-computed fields the client-facing `*Update` schema doesn't expose
  (e.g. `Book.available_copies`). This catches a typo'd or wrong-typed field
  at type-check time instead of at runtime. Repositories return DTOs
  (Pydantic schemas), never raw ORM models — services and routers never
  import SQLModel.
- `core/deps.py` is the only place that constructs a `SQLModelBackend(...)`
  and injects it — swapping ORM means writing one new `CrudBackend`
  implementation and changing the constructor calls there, not touching any
  module's `repositories.py`, `services.py`, or router.

`app/core/` holds cross-module infrastructure — nothing domain-specific
belongs here:

- `config.py` — `Settings` (pydantic-settings, reads `.env`), accessed only
  via the cached `get_settings()`, never `Settings()` directly (keeps it
  overridable via FastAPI's dependency system in tests).
- `db.py` — SQLModel `engine` + `get_session()` (FastAPI dependency) /
  `session_scope()` (context manager, for CLI scripts). Both commit on
  success, roll back on exception. Deliberately has no `create_all()`-style
  helper — schema is Alembic's job (`alembic upgrade head`), not this
  module's; the app's `lifespan` no longer auto-creates tables on boot.
- `model_registry.py` — imports every module's `models.py` so
  `SQLModel.metadata` knows about all tables. Imported by `alembic/env.py`
  (autogenerate needs every table registered to diff against) and by tests
  that build their own throwaway in-memory engine.
- `repository_interface.py` / `repository_sqlmodel.py` — the repository
  pattern's core machinery; see Architecture above.
- `service_utils.py` — `get_or_404()`, the shared "fetch or raise
  `NotFoundError`" helper every service's read/update/delete uses.
- `mappers.py` — `to_page()` / `pagination_offset()`, generic pagination helpers.
- `schemas.py` — `CamelModel` (snake_case Python <-> camelCase JSON),
  `PaginationParams`, generic `Page[T]`.
- `security.py` — JWT encode/decode (PyJWT), password hashing (bcrypt, not passlib).
- `token_denylist.py` — `InMemoryTokenDenylist`, keyed by JWT `jti`, for
  `/auth/logout`. In-memory/per-process — resets on restart, doesn't share
  state across worker processes (an accepted limitation at this project's scale).
- `rate_limiter.py` — `InMemoryRateLimiter`, a fixed-window counter keyed by
  client IP. `deps.py`'s `rate_limit_auth` dependency guards `/auth/login`
  and `/auth/register` with it, raising `TooManyRequestsError` past the
  configured limit (`AUTH_RATE_LIMIT_MAX_ATTEMPTS`/`_WINDOW_SECONDS`). Same
  in-memory/per-process pattern as `token_denylist.py`.
- `exceptions.py` — `AppError` and subclasses (`NotFoundError`, `ConflictError`,
  `AlreadyExistsError`, `UnauthorizedError`, `ForbiddenError`, `BadRequestError`,
  `TooManyRequestsError`), plain Python with no `fastapi` import. Domain
  modules raise these from services/repositories instead of `HTTPException`
  directly. `AlreadyExistsError` (a `ConflictError` subclass) is for
  duplicate-creation specifically (email/ISBN/category name already taken,
  book already borrowed, reservation already open); other conflicts
  (deleting a still-referenced row, borrow limit reached) stay plain `ConflictError`.
- `responses.py` — `ErrorResponse` (the `{code, message, errors}` shape —
  the HTTP status code itself is not repeated in the body). Success
  responses have no envelope — routers return the schema object directly
  via `response_model`.
- `error_handlers.py` — `register_exception_handlers(app)`, called once from
  the app factory. Translates `AppError` (and subclasses),
  `RequestValidationError`, and any unhandled `Exception` into the
  `ErrorResponse` shape — the only layer besides routers allowed to know
  about FastAPI/HTTP for error handling.
- `logging_config.py` — `setup_logging(debug)`, called once from the app factory
  (with `settings.debug`). Configures the root + uvicorn loggers with a
  shared handler/format and a `request_id_var` contextvar so every log line
  (including ones from `error_handlers.py`) carries the current request id.
- `middleware.py` — `register_middleware(app)`, called once from the app
  factory. Registers `RequestContextMiddleware` (sets `request_id_var` from
  the incoming `X-Request-ID` header or a fresh uuid4, echoes it on the
  response, logs one line per request) and `CORSMiddleware` (from
  `settings.cors_origins`), added last so it stays outermost.
- `ws_manager.py` — `ConnectionManager`, tracks live `/ws/notifications`
  sockets per user (a user can have more than one open tab).
- `notifications.py` — `Notifier`/`EmailSender` (ABCs) + `Notification`
  dataclass. `get_notifier()`/`set_notifier()` is a process-wide singleton
  every domain service depends on to push a notification, never on a
  concrete channel. `CompositeNotifier` fans one notification out to every
  channel it wraps (`WebSocketNotifier` + `EmailNotifier`, wired in
  `main.py`'s `lifespan`) — one channel failing doesn't block the others.
  `EmailNotifier` is deliberately DB-free (it only reads `Notification.email`,
  resolved by the calling service via its own `UserRepositoryInterface`)
  since the notifier singleton can't safely borrow a request-scoped session.
  `SMTPEmailSender` (stdlib `smtplib`) is real delivery; `InMemoryNotifier`/
  `InMemoryEmailSender` are the safe defaults tests and unconfigured dev/test
  fall back to when no SMTP host is configured.

`app/main.py` is an app factory (`create_app()`) building the `FastAPI`
instance; `lifespan` wires up logging and the notifier (no longer table
creation — see Migrations below); domain routers are registered with
`app.include_router(...)`.

## Migrations

Schema is managed by Alembic (`alembic/`), not an auto `create_all()` on
app startup — that auto-create path was removed on purpose (it was
silently creating tables in the real `library.db` on every app boot,
including under `TestClient` in tests, which papered over exactly the
problem migrations exist to solve). `alembic/env.py` sets
`target_metadata = SQLModel.metadata` (via `app.core.model_registry`, same
side-effect import `create_all()` used to rely on) and pulls the connection
URL from `app.core.config.get_settings().database_url` (`.env`) instead of
a second hardcoded copy in `alembic.ini`.

- `uv run alembic upgrade head` — apply all pending migrations (run this
  before first starting the app, and after pulling any new migration file).
- `uv run alembic revision --autogenerate -m "..."` — after changing a
  model, generate a migration. **Always review the generated file** —
  autogenerate is a starting point, not guaranteed correct.
- `uv run alembic downgrade -1` / `alembic current` / `alembic history`.
- Commit the migration file alongside the model change, same PR — never
  hand-edit a migration once it's been applied anywhere but your own machine.
- Tests are unaffected by any of this: they build their own throwaway
  in-memory SQLite engine and call `SQLModel.metadata.create_all()` on it
  directly (see `tests/conftest.py`'s `db_engine` fixture) — a deliberately
  separate, faster path from the real app's migrated schema.

## Testing

`tests/` mirrors `app/`: `tests/core/` for `app/core/*`, `tests/cli/` for
`app/cli/*`, `tests/modules/<name>/` for each `app/modules/<name>/` — e.g.
`tests/modules/book/` holds `test_routers.py`, `test_services.py`,
`test_models.py`, `test_repositories.py`, `test_schemas.py`. A few modules
have extra module-specific files alongside those (`borrowing/` also has
`test_lists.py`, `test_auto_reserve.py`, `test_notify_overdue.py`;
`reservation/` also has `test_notify.py`, `test_websocket.py`; `user/` also
has `test_auth_routers.py`/`test_auth_deps.py`/`test_auth_rate_limit.py`
alongside `test_admin_routers.py` since the module has two router files).
Generic, cross-module behavior (the repository pattern itself via
`SQLModelBackend`, `to_page`, `CamelModel`/`PaginationParams`, table
registration) lives in `tests/core/` instead of being duplicated per module.
Every subdirectory has an `__init__.py` (matching `tests/__init__.py` at the
root) so same-named files in different module folders (`test_models.py`,
`test_routers.py`, ...) don't collide under pytest's default import mode.

`tests/conftest.py` (at the root, so its fixtures reach every subfolder)'s
`client` fixture (`TestClient` over `app`) overrides `get_session` with an
in-memory SQLite engine (`StaticPool`) — a dependency override, not a mock —
so tests never touch `library.db`, and bypasses `rate_limit_auth` by default
(most tests register/log in several users per test;
`tests/modules/user/test_auth_rate_limit.py` re-enables it to test the real
thing). `member_token`/`admin_token` fixtures give a ready-made JWT for each
role. `tests/fakes.py` has an in-memory `Fake<Module>Repository` per module
implementing the real interface, for service-level unit tests with no DB at
all (see `tests/modules/book/test_services.py`,
`tests/modules/user/test_services.py`, etc.) — compare with the
same-behavior integration tests in `tests/modules/book/test_routers.py`/
`tests/modules/user/test_admin_routers.py` that go through the real HTTP
API + DB.

## Tech stack

- Python 3.12, FastAPI, SQLite + SQLModel, Alembic (migrations)
- uv (package manager), pydantic-settings
- PyJWT (JWT), bcrypt (password hashing — not passlib, see `app/core/security.py`)
- pytest + pytest-cov, ruff (lint + format), mypy, pre-commit
- httpx2 (Starlette `TestClient`'s transport — keep this dependency even
  though nothing imports it directly; removing it brings back a
  `StarletteDeprecationWarning` on every test run)

## Rules (MANDATORY)

- services.py must NEVER import from fastapi (no Depends, no HTTPException).
  Services raise domain exceptions (defined in core/exceptions.py); the global
  exception handler translates them into HTTP status codes.
- Routers do exactly 3 things: receive request → call service → return response.
- Response format: both success and error responses rely on the actual
  HTTP status code rather than repeating it in the body. Success responses
  have no envelope — the endpoint declares `response_model` and returns the
  schema object directly (200/201/204). Error responses are
  {code, message, errors}, built by the global exception handler.
- Book: availableCopies is the single source of truth; status is computed
  in the response, never stored independently.
- Static routes (/borrowings/history, /current, /overdue) must be declared
  BEFORE the path-param route /borrowings/{id}.
- Do NOT implement /auth/refresh.
- /auth/login and /auth/register are rate-limited (see `core/rate_limiter.py`)
  — don't add new public/anonymous endpoints without considering the same.
- A repository's `update()` takes a per-module `TypedDict` (see
  `repositories.py`), not a bare `dict[str, Any]` — when a service computes
  an extra field beyond what the client-facing `*Update` schema exposes
  (e.g. `Book.available_copies`), add it to that `TypedDict`, not a `cast(Any, ...)`.

## Business rules

- Roles: anonymous, member, admin
- A member can borrow at most 5 books concurrently (`Settings.borrow_limit`);
  loan duration is 14 days (`Settings.loan_duration_days`); overdue is
  computed on read (no background job for it) — an admin can trigger
  `POST /borrowings/notify-overdue` on demand to push reminders.
- Reservation: FIFO queue ordered by createdAt; when a book is returned,
  every member still pending on it is notified (not just the head of the
  queue) — via WebSocket /ws/notifications and email, fanned out through
  `CompositeNotifier` (using BackgroundTasks; see `app/core/notifications.py`).
  Only closed out ("fulfilled") once its owner actually borrows — see
  `ReservationService.notify_book_available`.
- Deleting a Book/Category/User that is still referenced returns 409 — for
  Book/User this means both active borrowings AND open reservations, not
  borrowings alone (a book/user with only an open reservation would
  otherwise hit an unhandled FK-constraint 500 instead of a clean 409).

## Git conventions

- Branches: feat/<short-description> or bugfix/<...>, merged into fastapi-practice-1
- Commit messages: capitalize the first letter
- MR titles: Implement/Integrate/Handle <content>
