# CLAUDE.md

Library management API (FastAPI, SQLModel, SQLite). When extending a module, match the existing layering. `app/modules/category/` is the canonical example.

## Commands

```bash
uv sync
uv run alembic upgrade head   # before first run and after pulling a new migration
uv run fastapi dev
uv run pytest
uv run ruff check . && uv run ruff format .
uv run mypy                   # app/ only
uv run pre-commit run --all-files
```

- Smoke check: `curl http://127.0.0.1:8000/health`.
- `uv run python -m app.cli.seed_admin` is the only way to create an admin. `/auth/register` always creates a `member`.
- `uv run python -m app.cli.seed_demo --force` seeds demo data.

## Architecture

- Dependency direction: routers → services → repositories → models. Routers never call repositories.
- Services depend on the repository interface (`repositories.py`), never the concrete class.
- Only `repositories_sqlmodel.py` may import `sqlmodel` or the table model.
- Repositories return DTOs (Pydantic schemas), never ORM models.
- In the app, only `core/deps.py` constructs `SQLModelBackend`. CLI scripts construct their own.
- `app/core/` is cross-module only. Nothing domain-specific goes there.
- Read settings via the cached `get_settings()`, never `Settings()`. Tests override it.
- Raise `AlreadyExistsError` for duplicate creation (email, ISBN, category name, book already borrowed, reservation already open). Use plain `ConflictError` for other conflicts (deleting a referenced row, borrow limit reached).
- `EmailNotifier` must stay DB-free. The calling service fills `Notification.email`. The notifier singleton cannot use a request-scoped session.

## Migrations

- Alembic owns the schema. Never add `create_all()` to the app. It was removed because it silently created tables in `library.db`, even under tests.
- After a model change, run `uv run alembic revision --autogenerate -m "..."`. Always review the generated file.
- Commit the migration with the model change, in the same PR.
- Never edit a migration that has been applied outside your own machine.

## Testing

- `tests/` mirrors `app/`. Every test directory needs an `__init__.py`, or same-named test files collide.
- Tests build their own in-memory SQLite engine with `create_all()`. This is intended and separate from migrations.
- The `client` fixture (`tests/conftest.py`) bypasses `rate_limit_auth`. `tests/modules/user/test_auth_rate_limit.py` re-enables it.
- Use the `member_token` / `admin_token` fixtures for auth.
- Service unit tests use the fake repositories in `tests/fakes.py`, with no DB.

## Rules (MANDATORY)

- `services.py` never imports `fastapi`. Services raise exceptions from `core/exceptions.py`. The global handler maps them to HTTP codes.
- Routers do exactly 3 things: receive request → call service → return response.
- Success responses have no envelope. Declare `response_model` and return the schema.
- Error body is `{code, message, errors}`, built by the global handler. Never repeat the status code in the body.
- Declare static routes before routes with a path param.
- Do NOT implement `/auth/refresh`.
- `/auth/login` and `/auth/register` are rate-limited. Consider the same for any new anonymous endpoint.
- Repository `update()` takes the module's `TypedDict` (e.g. `BookUpdateFields`). Add service-computed fields there. Never use `cast(Any, ...)`.
- Keep the `httpx2` dev dependency even though nothing imports it. Removing it brings back a `StarletteDeprecationWarning`.

## Business rules

- Roles: anonymous, member, admin.
- Book: `availableCopies` is the single source of truth. `status` is computed in the response, never stored.
- A member borrows at most 5 books (`Settings.borrow_limit`). Loans last 14 days (`Settings.loan_duration_days`).
- Overdue is computed on read. There is no background job. Admins send reminders via `POST /borrowings/notify-overdue`.
- Reservations are a FIFO queue by `createdAt`. On return, notify every pending member, not just the head (WebSocket + email via `CompositeNotifier`).
- A reservation is fulfilled only when its owner borrows the book.
- Deleting a referenced Book/Category/User returns 409. For Book/User, check both active borrowings and open reservations.

## Git

- Branches: `feat/<short-description>` or `bugfix/<...>`, merged into `dev`.
- Commit messages start with a capital letter.
- MR titles: Implement/Integrate/Handle <content>.
