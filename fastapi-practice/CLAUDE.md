# CLAUDE.md

Library management API (FastAPI, SQLModel, SQLite). When extending a module, match the existing layering. `app/modules/category/` is the canonical example.

## North star

Every library business rule has tests, and every change reaches dev via PR with green CI.

## Commands

```bash
# from repo root: cd fastapi-practice
uv sync
uv run alembic upgrade head   # human-run only, see Migrations
uv run fastapi dev
uv run pytest                 # ok: "N passed"
uv run ruff check . && uv run ruff format <changed .py files>   # ok: "All checks passed!"
uv run mypy                   # app/ and tests/; ok: "Success: no issues found in N source files"
uv run pre-commit run --all-files   # config: ../.pre-commit-config.yaml (git root), scoped to fastapi-practice/
```

- Smoke check: `curl http://127.0.0.1:8000/health`.
- `uv run python -m app.cli.seed_admin` is the only way to create an admin. `/auth/register` always creates a `member`. `uv run python -m app.cli.seed_demo --force` seeds demo data.

## Architecture

- Dependency direction: routers → services → repositories → models. Routers do exactly 3 things: receive request → call service → return response. They never call repositories.
- Services depend on the repository interface (`repositories.py`), never the concrete class.
- Only `repositories_sqlmodel.py` may import `sqlmodel` or the table model. Repositories return DTOs (Pydantic schemas), never ORM models.
- In the app, only `core/deps.py` constructs `SQLModelBackend`. CLI scripts construct their own.
- `app/core/` is cross-module only. Nothing domain-specific goes there.
- `EmailNotifier` must stay DB-free. The calling service fills `Notification.email`. The notifier singleton cannot use a request-scoped session.

## Migrations

- Alembic owns the schema. `alembic upgrade` is run by a human, before first run and after pulling a new migration. Claude never runs it: a `PreToolUse` hook (`.claude/hooks/block-forbidden-commands.sh`) blocks it. When a migration needs applying, ask the user.
- After a model change, run `uv run alembic revision --autogenerate -m "..."`. Always review the generated file.
- Commit the migration with the model change, in the same PR. Never edit a migration that has been applied outside your own machine.

## Testing

- `tests/` mirrors `app/`. Every test directory needs an `__init__.py`, or same-named test files collide. Tests build their own in-memory SQLite engine with `create_all()`. This is intended and separate from migrations.
- The `client` fixture (`tests/conftest.py`) bypasses `rate_limit_auth`. `tests/modules/user/test_auth_rate_limit.py` re-enables it.
- Use the `member_token` / `admin_token` fixtures for auth. Service unit tests use the fake repositories in `tests/fakes.py`, with no DB.
- Before reporting a task done, run `uv run pytest`, `uv run ruff check .` and `uv run mypy`, and paste the summary line of each (see Commands).
- When fixing a bug, add a regression test. Never edit or delete an existing test. If one looks wrong, stop and ask the user.

## Rules (MANDATORY)

- Read docs/decisions.md before changing a design. When a PR settles a new decision, add one line to it in the same PR.
- `services.py` never imports `fastapi`. Services raise exceptions from `core/exceptions.py` and the global handler maps them to HTTP codes: `AlreadyExistsError` for duplicate creation (email, ISBN, category name, book already borrowed, reservation already open), plain `ConflictError` for other conflicts (deleting a referenced row, borrow limit reached).
- Success responses have no envelope. Declare `response_model` and return the schema. Error body is `{code, message, errors}`, built by the global handler. Never repeat the status code in the body.
- Declare static routes before routes with a path param.
- `/auth/login` and `/auth/register` are rate-limited. Consider the same for any new anonymous endpoint.
- Repository `update()` takes the module's `TypedDict` (e.g. `BookUpdateFields`). Add service-computed fields there.

## Things Claude gets wrong

- Adding `create_all()` to the app. It was removed because it silently created tables in `library.db`, even under tests.
- Calling `Settings()`. Use the cached `get_settings()`, which tests override.
- Using `cast(Any, ...)` to get past `update()` typing. Extend the module's `TypedDict` instead.
- Removing the unused `httpx2` dev dependency. It keeps a `StarletteDeprecationWarning` away.
- Implementing `/auth/refresh`. Do NOT.
- `ruff format .`: it also formats code blocks inside `.md` files. Format only the `.py` files you changed.
- `/code-review` without a range: `main` is empty, so always pass one (e.g. `dev...HEAD`).
- Writing non-UTC datetimes to SQLite. It drops the offset without converting, so a `+07:00` value is stored as local time. Always write UTC.
- Working around a blocked command. When a hook blocks one, stop and ask the user instead of finding another way.

## Business rules

- Roles: anonymous, member, admin.
- Book: `availableCopies` is the single source of truth. `status` is computed in the response, never stored. A member borrows at most 5 books (`Settings.borrow_limit`). Loans last 14 days (`Settings.loan_duration_days`).
- Overdue is computed on read. There is no background job. Admins send reminders via `POST /borrowings/notify-overdue`.
- A return after `due_date` records a ban for `Settings.late_return_ban_days` (default 7, `0` = off; bans never stack, the later end date wins). `borrow()` does not enforce it yet (see #41).
- Reservations are a FIFO queue by `createdAt`. On return, notify every pending member, not just the head (WebSocket + email via `CompositeNotifier`). A reservation is fulfilled only when its owner borrows the book.
- Deleting a referenced Book/Category/User returns 409. For Book/User, check both active borrowings and open reservations.

## Git

- Branches: `feat/<short-description>` or `bugfix/<...>`, merged into `dev`. Never push straight to `dev` or `main`: the same `PreToolUse` hook blocks it.
- Commit messages start with a capital letter. MR titles: Implement/Integrate/Handle <content>.
