# Library Management System

A FastAPI-based REST API for managing books, categories, users, borrowings,
and reservations.

## Target

- Understand and apply core concepts of FastAPI in a real project
- Design and implement relational database models with proper relationships
- Build CRUD APIs with request/response validation (Pydantic)
- Implement authentication and role-based authorization (JWT, OAuth2)
- Apply repository pattern and dependency injection (clean architecture)
- Handle background tasks and WebSocket for real-time features
- Write unit and integration tests

## Timeline

10 days.

## Requirements

**Anonymous**

- Browse and search books
- Filter books by category / author
- Register an account

**Member**

- Login / logout (JWT)
- Borrow up to 5 books at once
- Return books
- View borrowing history
- Reserve a book that's currently unavailable
- Receive a WebSocket notification when a reserved book becomes available

**Admin**

- CRUD on books, categories, and users
- View all borrowings, including overdue ones (loan duration: 14 days)

## Tech Stack

- [Python 3.12](https://docs.python.org/3.12/)
- [FastAPI](https://fastapi.tiangolo.com/)
- [SQLite](https://www.sqlite.org/) + [SQLModel](https://sqlmodel.tiangolo.com/)
- [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) — env-based `Settings`
- [PyJWT](https://pyjwt.readthedocs.io/) — JWT encode/decode
- [bcrypt](https://pypi.org/project/bcrypt/) — password hashing
- [pytest](https://docs.pytest.org/) + [pytest-cov](https://pytest-cov.readthedocs.io/) — tests and coverage reporting
- [httpx](https://www.python-httpx.org/) — HTTP client used by FastAPI's `TestClient`

## Project Structure

`__init__.py` files are omitted below for readability.

```
fastapi/practice/
├── app/
│   ├── main.py                      # FastAPI app factory + GET /health
│   ├── cli/
│   │   ├── seed_admin.py            # uv run python -m app.cli.seed_admin
│   │   └── seed_demo.py             # uv run python -m app.cli.seed_demo --force
│   ├── core/                        # cross-cutting infrastructure, shared by every module
│   │   ├── config.py                # Settings (pydantic-settings) + get_settings()
│   │   ├── db.py                    # SQLModel engine + get_session() / session_scope()
│   │   │                            # (schema itself is Alembic's job, not this module's)
│   │   ├── deps.py                  # get_current_user / require_admin / get_*_service
│   │   ├── security.py              # JWT encode/decode (PyJWT), password hashing (bcrypt)
│   │   ├── token_denylist.py        # in-memory denylist for logged-out access tokens
│   │   ├── rate_limiter.py          # in-memory rate limiter for /auth/login, /auth/register
│   │   ├── ws_manager.py            # per-user WebSocket connection registry
│   │   ├── notifications.py         # Notifier/EmailSender interfaces + InMemory/WebSocket/
│   │   │                            # SMTP/Composite implementations
│   │   ├── repository_interface.py  # CrudBackend + CrudRepositoryInterface (ORM-agnostic)
│   │   ├── repository_sqlmodel.py   # SQLModelBackend (the one CrudBackend impl) + apply_filters()
│   │   ├── service_utils.py         # get_or_404() — service-layer fetch-or-404 helper
│   │   ├── mappers.py               # to_page() + pagination_offset() — pagination helpers
│   │   ├── schemas.py               # CamelModel base, Page / PaginationParams
│   │   ├── model_registry.py        # imports every module's models.py for SQLModel metadata
│   │   ├── responses.py             # ErrorResponse
│   │   ├── exceptions.py            # AppError and subclasses (domain exceptions)
│   │   ├── error_handlers.py        # register_exception_handlers(app)
│   │   ├── logging_config.py        # setup_logging(debug) + request_id_var
│   │   └── middleware.py            # RequestContextMiddleware + CORS, register_middleware(app)
│   └── modules/
│       ├── category/                # canonical 7-file module layout
│       │   ├── models.py            # SQLModel table
│       │   ├── schemas.py           # Pydantic request/response DTOs
│       │   ├── mappers.py           # model -> schema mapping
│       │   ├── repositories.py      # ABC interface, extends core's CrudRepositoryInterface
│       │   ├── repositories_sqlmodel.py  # concrete implementation — the only file allowed
│       │   │                        # to import the SQLModel table / `sqlmodel` itself
│       │   ├── services.py          # business logic — no fastapi import
│       │   └── routers.py           # /categories/* endpoints
│       ├── book/                    # same layout as category/ — /books/* endpoints
│       ├── borrowing/               # same layout as category/ — /borrowings/* endpoints
│       ├── user/                    # same layout as category/, plus:
│       │   ├── enums.py             # UserRole
│       │   ├── routers.py           # self-service /auth/* endpoints (not /users/*)
│       │   └── admin_routers.py     # + admin-only /users/* endpoints
│       └── reservation/             # same layout as category/ — /reservations/* endpoints, plus:
│           ├── enums.py             # ReservationStatus
│           └── ws_routers.py        # /ws/notifications WebSocket endpoint
├── tests/
│   ├── conftest.py                  # client / db_engine / member_token / admin_token /
│   │                                 # auth_headers fixtures
│   ├── fakes.py                     # in-memory Fake<Module>Repository per module
│   ├── core/                        # tests for app/core/* (config, db, deps, middleware,
│   │                                 # error_handlers, mappers, notifications, rate_limiter,
│   │                                 # repository pattern itself, schemas, security, health)
│   ├── cli/                         # tests for app/cli/* (seed_admin, seed_demo)
│   └── modules/                     # mirrors app/modules/ — one folder per domain module,
│       ├── book/                    # each with test_routers.py, test_services.py,
│       ├── category/                # test_models.py, test_repositories.py, test_schemas.py
│       ├── borrowing/                #   (borrowing/reservation/user also have extra
│       ├── reservation/               #   module-specific files — auto_reserve, notify,
│       └── user/                        #   websocket, auth_routers/auth_deps, admin_routers...)
├── alembic/                          # migration environment — see "Database Migrations" below
│   ├── env.py                        # target_metadata = SQLModel.metadata, url from Settings
│   └── versions/
│       └── b1ffdb205e3c_initial_schema.py
├── alembic.ini
├── .env.example
├── pyproject.toml
├── uv.lock
└── .pre-commit-config.yaml
```

Cross-cutting infrastructure lives in `app/core/`; every domain module
(`book/`, `borrowing/`, `category/`, `reservation/`, `user/`) follows the
same layout, spelled out once for `category/` above and expressed as a diff
for the rest rather than repeating all seven files five times.

## Architecture

Layered / clean architecture with the repository pattern, applied per
module. Each domain module follows a strict dependency direction —
`routers.py` (thin HTTP layer) → `services.py` (business logic, raises
domain exceptions, never imports `fastapi`) → `repositories.py` (an ABC
interface extending `core/repository_interface.py`'s `CrudRepositoryInterface`,
backed by `repositories_sqlmodel.py`'s concrete implementation) → `models.py`
(SQLModel tables). A repository forwards its 5 generic CRUD methods to an
injected `CrudBackend` (composition, not inheritance) so swapping ORM means
writing one new backend, not touching any module. Cross-cutting
infrastructure — config, DB engine, logging, middleware, exception handling,
response format — lives in `app/core/` and is shared by every module.

```
Client
  │
  ▼
Router        FastAPI endpoint — receives request, calls a service, returns
  │           the response in the standard format
  ▼
Service       business logic — raises AppError subclasses, no fastapi import
  │
  ▼
Repository    ABC interface + concrete SQLModel implementation, composed
  │           with a CrudBackend for the 5 generic CRUD methods
  ▼
SQLite        via the SQLModel engine (app/core/db.py)

Any AppError raised along the way propagates up and is caught by the global
exception handler (app/core/error_handlers.py), which turns it into the
standard error response — routers never build error responses by hand.
```

## API Response Format

Success responses have no envelope — the endpoint returns the resource
(or paginated `Page[...]`) directly, and the HTTP status code (200/201/204)
conveys success:

```json
{
  "id": 1,
  "title": "Clean Architecture"
}
```

Error responses also rely on the HTTP status code (404, 409, ...) rather
than repeating it in the body:

```json
{
  "code": "NOT_FOUND",
  "message": "Book not found",
  "errors": null
}
```

## Roles & Permissions

| Role      | Access                                                                                                                                                                         |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Anonymous | Browse/search books, filter by category, register                                                                                                                              |
| Member    | Login/logout (JWT), borrow up to 5 books, return books, view borrowing history, reserve unavailable books, receive WebSocket notification when a reservation becomes available |
| Admin     | CRUD books/categories/users, view all borrowings and overdue ones                                                                                                              |

## API Endpoints

Generated from the actual routers (`app/modules/*/routers.py`,
`app/modules/reservation/ws_routers.py`). "Auth" is the minimum role
required — Admin routes require a logged-in admin, Member routes require
any logged-in user.

### Auth (`/auth`)

| Method | Path           | Auth      | Purpose                                    |
| ------ | -------------- | --------- | ------------------------------------------ |
| POST   | /auth/register | Anonymous | Register a new member account              |
| POST   | /auth/login    | Anonymous | Log in, get a JWT access token             |
| POST   | /auth/logout   | Member    | Revoke (denylist) the current access token |
| GET    | /auth/me       | Member    | Get the current authenticated user         |

`/auth/register` and `/auth/login` are rate-limited per client IP (default:
5 attempts / 60s, see `AUTH_RATE_LIMIT_MAX_ATTEMPTS`/`AUTH_RATE_LIMIT_WINDOW_SECONDS`
in `.env.example`) — exceeding it returns 429 `TOO_MANY_REQUESTS`.

### Categories (`/categories`)

| Method | Path                      | Auth      | Purpose                                     |
| ------ | ------------------------- | --------- | ------------------------------------------- |
| GET    | /categories               | Anonymous | List categories                             |
| GET    | /categories/{category_id} | Anonymous | Get a category by id                        |
| POST   | /categories               | Admin     | Create a category                           |
| PATCH  | /categories/{category_id} | Admin     | Update a category                           |
| DELETE | /categories/{category_id} | Admin     | Delete a category (409 if still referenced) |

### Books (`/books`)

| Method | Path             | Auth      | Purpose                                                |
| ------ | ---------------- | --------- | ------------------------------------------------------ |
| GET    | /books           | Anonymous | List/search books (`q`, `categoryId`, `availableOnly`) |
| GET    | /books/{book_id} | Anonymous | Get a book by id                                       |
| POST   | /books           | Admin     | Create a book                                          |
| PATCH  | /books/{book_id} | Admin     | Update a book                                          |
| DELETE | /books/{book_id} | Admin     | Delete a book (409 if still referenced)                |

### Users (`/users`, admin-only)

| Method | Path             | Auth  | Purpose                                   |
| ------ | ---------------- | ----- | ----------------------------------------- |
| GET    | /users           | Admin | List users (filter by `role`, `isActive`) |
| GET    | /users/{user_id} | Admin | Get a user by id                          |
| POST   | /users           | Admin | Create a user (any role)                  |
| PATCH  | /users/{user_id} | Admin | Update a user                             |
| DELETE | /users/{user_id} | Admin | Delete a user (409 if still referenced)   |

### Borrowings (`/borrowings`)

| Method | Path                              | Auth   | Purpose                                      |
| ------ | --------------------------------- | ------ | -------------------------------------------- |
| GET    | /borrowings/history               | Member | Current user's borrowing history             |
| GET    | /borrowings/current               | Member | Current user's active borrowings             |
| GET    | /borrowings/overdue               | Admin  | List overdue borrowings (all users)          |
| GET    | /borrowings                       | Admin  | List all borrowings (optional `overdueOnly`) |
| POST   | /borrowings                       | Member | Borrow a book — see "Borrow behavior" below  |
| POST   | /borrowings/{borrowing_id}/return | Member | Return a borrowed book                       |

### Reservations (`/reservations`)

| Method | Path                           | Auth   | Purpose                             |
| ------ | ------------------------------ | ------ | ----------------------------------- |
| GET    | /reservations/my               | Member | Current user's reservations         |
| POST   | /reservations                  | Member | Reserve a book                      |
| DELETE | /reservations/{reservation_id} | Member | Cancel one of your own reservations |

### WebSocket

| Method    | Path                            | Auth   | Purpose                                      |
| --------- | ------------------------------- | ------ | -------------------------------------------- |
| WebSocket | /ws/notifications?token=`<jwt>` | Member | Realtime `BOOK_AVAILABLE` push notifications |

### Borrow behavior

`POST /borrowings` returns:

- **201** — the book was available and is now borrowed; `data` is the new
  borrowing.
- **202** — the book was unavailable at the moment of the request (a race
  between the client seeing it as available and the request landing); the
  member is auto-added to the reservation queue instead, and `data` is the
  resulting reservation. This is a safety net, not the primary reservation
  path — to proactively reserve a book that's already known to be
  unavailable, call `POST /reservations` directly.

### Realtime Notifications

Connect to `ws://<host>/ws/notifications?token=<jwt>` with a valid access
token passed as the `token` query parameter (WebSocket clients can't send a
custom `Authorization` header, so auth goes through the query string
instead of a bearer header). Each connection is scoped to the authenticated
user. When a book someone has reserved is returned, the server pushes a
`BOOK_AVAILABLE` message to every pending/notified reserver's open
connection(s) for that user.

An admin can also trigger `POST /borrowings/notify-overdue` on demand to
push an `OVERDUE_REMINDER` message to every member currently holding an
overdue book, through the same notification pipeline — no scheduler
involved, it's a plain scan-and-notify on request. (Future work: a
scheduler/cron could call this endpoint automatically instead of relying on
an admin to trigger it.)

## Getting Started

1. Clone the repository:

   ```bash
   git clone git@gitlab.asoft-python.com:nguyet.tran/python-training.git
   cd python-training
   ```

2. Checkout the practice branch:

   ```bash
   git checkout fastapi-practice-1
   ```

3. Navigate to the project folder:

   ```bash
   cd fastapi/practice
   ```

4. Install [uv](https://docs.astral.sh/uv/) if you don't have it yet.

5. Install dependencies (creates `.venv`):

   ```bash
   uv sync
   ```

6. Set up environment variables:

   ```bash
   cp .env.example .env
   ```

   Edit `.env` and fill in real values — in particular `JWT_SECRET_KEY`,
   which is required and has no default.

7. Run database migrations (creates `library.db` with all tables — the app
   no longer auto-creates schema on boot, see "Database Migrations" below):

   ```bash
   uv run alembic upgrade head
   ```

## Database Migrations

Schema is managed by [Alembic](https://alembic.sqlalchemy.org/), not by an
auto `create_all()` on app startup — `alembic/env.py` points
`target_metadata` at `SQLModel.metadata` (via `app.core.model_registry`) and
reads the connection URL from `Settings.database_url` (`.env`), so it always
targets the same DB the app itself uses.

```bash
uv run alembic upgrade head                       # apply all pending migrations
uv run alembic revision --autogenerate -m "..."    # after changing a model, generate a migration
uv run alembic downgrade -1                        # roll back the last migration
uv run alembic current                             # show the currently-applied revision
uv run alembic history                             # list all revisions
```

Workflow when a model changes (e.g. adding a field to `Book`):

1. Edit the model in `app/modules/<name>/models.py`.
2. `uv run alembic revision --autogenerate -m "Add <field> to <table>"`.
3. **Review** the generated file in `alembic/versions/` — autogenerate is a
   starting point, not guaranteed correct (it can miss data backfills,
   column renames show up as drop+add, etc.).
4. `uv run alembic upgrade head` to apply it locally, then commit the
   migration file alongside the model change in the same PR.

Never hand-edit a migration that's already been applied anywhere but your
own machine — write a new one instead, the same rule as regular git commits.

## Seed the First Admin

`POST /auth/register` always creates a `member` (see `AuthService.register`)
— there's no API route that produces an admin, so the first one has to come
from this CLI script:

```bash
uv run python -m app.cli.seed_admin --email admin@gmail.com --full-name "Admin"
```

## Demo Data

`app/cli/seed_demo.py` is separate from `seed_admin.py` above — it seeds
only the small, fixed set of things that are tedious to create by hand
through the API before a live demo. Everything else (borrowing a book,
reserving one, watching a WebSocket notification fire) is meant to be done
live, so the seeded data is deliberately minimal and non-entangled — no
reservations, and every book below starts fully available:

```bash
uv run python -m app.cli.seed_demo --force
```

## Running the Server

```bash
uv run fastapi dev
```

API docs are available at <http://127.0.0.1:8000/docs> once the server is
running. `GET /health` is a plain smoke check with no auth and no DB access.

## Testing

```bash
uv run pytest                                          # run the full suite
uv run pytest tests/core/test_health.py                # run a single file
uv run pytest tests/modules/book/                      # run every test for one module
uv run pytest --cov=app --cov-report=term-missing      # run with coverage
```

Coverage is configured in `pyproject.toml` (`[tool.coverage.run]` /
`[tool.coverage.report]`), scoped to `app/` with `tests/` omitted.

## Pre-commit

```bash
uv run pre-commit install          # one-time: install the git hook
uv run pre-commit run --all-files  # run all hooks against the whole project
```

`.pre-commit-config.yaml` (scoped to `fastapi/practice/`) runs `ruff-check
--fix` and `ruff-format`, plus the standard `pre-commit-hooks`: trailing
whitespace, end-of-file-fixer, YAML validity, merge-conflict markers, debug
statements, and large-file checks.
