---
name: how-we-write-router-tests
description: Write router tests for an endpoint in this repo's style. Use when adding tests for a new or existing endpoint, e.g. "add 401 tests for reservation" or "write tests for POST /books". Not for service tests (fake repos) or refactoring existing tests.
---

Follow the test rules in CLAUDE.md (in-memory SQLite, member_token/admin_token). Add new tests only; do not change existing tests or helpers.

## Rules

1. Naming: one class per endpoint, `Test<Action><Resource>`. Test functions: `test_<condition>_returns_<status>`.
2. Error asserts: always check both `response.status_code` and `response.json()["code"]`.
3. Cases per endpoint: happy path; 401 if it needs auth; 403 if admin-only; 404 if the path has an id; 422 if it has a body; 409 if a conflict rule applies.
4. Data: use conftest fixtures (`client`, `member_token`, `admin_token`, `auth_headers`). Reuse a helper already in the same test file; do not create shared helpers or edit existing ones.

## Steps

1. Read the endpoint in `app/modules/<name>/routers.py` and its existing test file.
2. List the cases from rule 3 that are missing, then write them.
3. Run `uv run pytest <test file> -v`, then `uv run ruff check <test file>` and `uv run ruff format <test file>`.
4. Report the cases added and the test results.
