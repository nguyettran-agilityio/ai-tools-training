---
name: how-we-write-migrations
description: Write an Alembic migration for a SQLModel model change in this repo (new table, new/changed column) and hand it to a reviewer. Use when a task edits app/modules/*/models.py or asks for a migration. Not for seeding data, test DB setup (tests use create_all), or editing an already-shared migration.
---

# How we write migrations

Read the "Migrations" section of CLAUDE.md first; this skill adds the
team workflow on top of it. The README workflow ("Database Migrations")
applies. `DATABASE_URL` is `sqlite:///./library.db` (relative), so each
checkout/worktree has its own local DB: upgrade only your local DB.

## Steps

1. Change the model in `app/modules/<name>/models.py`. For a new table,
   also import it in `app/core/model_registry.py`, or autogenerate
   will not see it.
2. Check `uv run alembic current` against `uv run alembic heads`.
   Autogenerate diffs against the live DB, so if they differ, run
   `uv run alembic upgrade head` on the local DB first.
3. `uv run alembic revision --autogenerate -m "Add <field> to <table>"`
   (capitalised, like `25fd052b6468_add_renewed_at_to_borrowing.py`).
4. Review the generated file in `alembic/versions/`:
   - only the intended changes (no stray drops from an out-of-date DB);
   - `down_revision` points at the previous head;
   - `downgrade()` exactly reverses `upgrade()`;
   - renames show up as drop + add, so rewrite them by hand;
   - `alter_column` or a constraint change → stop and ask the user:
     SQLite needs batch mode and `env.py` does not set `render_as_batch`.
5. New column on a table that already has rows → `nullable=True`, no
   backfill, matching `renewed_at` (model field `X | None = None`). If a
   NOT NULL column or a backfill is really needed, ask the user first.
6. `uv run alembic upgrade head` to confirm the migration applies on the
   local DB.
7. `uv run ruff check --fix alembic/versions/<new_file>.py && uv run ruff format alembic/versions/<new_file>.py`
   on the new file only, never the whole folder (merged migrations must
   not change). Committed migrations use `str | Sequence[str] | None`.
8. `uv run pytest`. Tests use their own in-memory DB, so this checks the
   model, not the migration.
9. Commit the migration together with the model change (same PR). In the
   PR description, give the revision id and note "applied on local SQLite".

## Never

- Run `alembic downgrade` or `stamp`, or delete/replace the DB.
- Point `DATABASE_URL` at a DB that is not local.
- Edit a migration that is already merged or applied elsewhere; write a
  new one instead.
- Add `create_all()` to the app.
