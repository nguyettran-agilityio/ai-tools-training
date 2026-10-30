# Plan — #42 Admin report: overdue loans and late returns

Ticket: #42 (part of #39) · Branch: `feat/overdue-reports` → `dev`
Spec: [spec.md](spec.md) §5.1, §5.3, §5.4, §5.5, §5.6 · Tests: [test-matrix.md](test-matrix.md) TC-42-01 – TC-42-18

Admins get two reports that show the member's email and the book title next to each loan:

- `GET /borrowings/reports/overdue`: unreturned loans past their due date, newest borrow first.
- `GET /borrowings/reports/late-returns`: loans returned after their due date, newest return first, with optional inclusive `from` / `to` bounds.

Decisions this plan relies on:

- A new per-page cache helper is used only by the two reports. `notify_overdue` is unchanged (Dev Q1, agreed by BA).
- **A date-only `to` (`YYYY-MM-DD`) means the end of that day in UTC** (`23:59:59.999999Z`, inclusive). This is a new BA decision. It replaces the agreed Dev Q2 comment, which kept midnight. A date-only `from` stays at midnight UTC, so `from=to=2026-11-01` covers the whole of Nov 1. The `from > to` check uses the end-of-day value, so `from=2026-11-01T12:00:00Z&to=2026-11-01` is valid. Recorded as B-42-2 in spec §10.1 (PR #47).
- `from > to` returns 400 `BAD_REQUEST` with `errors: null` (Q-42-2). An invalid `from` or `to` returns 422 (Q-42-3). Any offset is converted with `astimezone(UTC)` (Q-42-4). Pagination uses the shared `PaginationParams` (Q-42-5). No secondary sort (Q-42-6).
- If a user or book is missing during enrichment, `LookupError` is raised. This should never happen, because borrowings cascade on delete (Q-42-1).

No model change, so no migration.

## Files that change

| File | Change |
|---|---|
| `app/modules/borrowing/schemas.py` | Adds `BorrowingReportRow(BorrowingRead)` with `user_email` and `book_title`; it keeps the computed `status`. Adds `_date_only_to_end_of_day`, which runs on the raw string before parsing. Adds `ReportUpperBound = Annotated[datetime, BeforeValidator(...)]`. |
| `app/modules/borrowing/repositories.py` | Adds `list_late_returns(offset, limit, returned_from, returned_to)` to `BorrowingRepositoryInterface`. |
| `app/modules/borrowing/repositories_sqlmodel.py` | Implements `list_late_returns`. Filters on `returned_at IS NOT NULL AND returned_at > due_date`; optional inclusive bounds go through `apply_filters`; orders by `returned_at DESC`. |
| `app/modules/borrowing/services.py` | Adds `_as_utc_bound` (naive → UTC, offset → `astimezone(UTC)`). Adds `report_overdue` (reuses `list_all(overdue_only=True, now)`) and `report_late_returns` (raises `BadRequestError` when `from > to`). Adds the `_to_report_rows` per-page cache (one `get_by_id` per distinct user and book), which raises `LookupError` on a missing reference. |
| `app/modules/borrowing/routers.py` | Adds two admin routes in the "Static routes" block. `from` / `to` use `Query(alias=...)` because `from` is a Python keyword. |
| `tests/fakes.py` | Adds `FakeBorrowingRepository.list_late_returns` with the same filter, bounds and order. |
| `tests/modules/borrowing/test_repositories.py` | Adds the `TestListLateReturns` class. |
| `tests/modules/borrowing/test_reports.py` (new) | Service tests with fakes, including counting fakes for the per-page cache. |
| `tests/modules/borrowing/test_schemas.py` | Adds the `TestReportUpperBound` class. |
| `tests/modules/borrowing/test_routers.py` | Adds the `TestReports` class, with one test per TC-42-15 – TC-42-18. |

## Order of work

1. Schemas: `BorrowingReportRow`, the date-only `to` validator, `ReportUpperBound`.
2. Repository: interface method, then the SQLModel implementation, then the fake.
3. Service: `_as_utc_bound`, `_to_report_rows`, `report_overdue`, `report_late_returns`.
4. Router: the two static routes.
5. Tests: repository, service, schema, router.
6. Format only the changed `.py` files. Then run `ruff check .`, `mypy`, and `pytest`.
7. Stop for review. No commit or push.

## Risks

- **SQLite ignores offsets when comparing datetimes.** A `+07:00` bound would be compared as if it were UTC. Mitigation: the service always calls `astimezone(UTC)`. A router test runs against real SQLite with `+07:00` values on both `from` and `to`.
- **A date-only `to` cannot be detected after parsing.** `2026-11-01` and `2026-11-01T00:00:00` give the same `datetime`. Mitigation: a `BeforeValidator` checks the raw string against `^\d{4}-\d{2}-\d{2}$`. Anything else, including invalid dates such as `2026-13-01`, goes through the normal parsing and gets its 422.
- **Two admin overdue lists now overlap** (`/borrowings/overdue` and `/borrowings/reports/overdue`). The Lead accepted this in C-17. A regression test checks that the old endpoints still return plain `BorrowingRead`.
- **Enrichment cost.** A page costs at most 200 extra single-row lookups, because `pageSize` is at most 100 (C-18). A JOIN query is out of scope.
- **Tie order.** There is no secondary sort (Q-42-6). Test fixtures avoid equal timestamps, or compare tied rows as a set.
- **mypy and nullable columns.** `Borrowing.returned_at` is typed `datetime | None`, so comparisons need `col()`.

## Proof

Commands run (format only on changed files):

```bash
uv run ruff format <changed .py files>
uv run ruff check .        # All checks passed
uv run mypy                # Success: no issues found in 128 source files
uv run pytest              # 385 passed
```

Test-matrix coverage:

| Case | Where |
|---|---|
| TC-42-01 overdue content and order | router `test_overdue_report_rows_order_and_utc_z_datetimes`; service `TestReportOverdue` |
| TC-42-02 pagination | router `test_overdue_report_pages_do_not_overlap`; repository `test_paginates_and_returns_utc_aware_datetimes` |
| TC-42-03 late-returns content, exactly-at-D excluded | repository `test_only_returns_after_due_date_newest_return_first`; router `test_late_returns_contents_order_and_utc_z_datetimes` |
| TC-42-04 inclusive bounds | repository `test_both_bounds_are_inclusive`; router `test_late_returns_bounds` |
| TC-42-05 naive datetime = UTC | service `test_naive_bound_is_treated_as_utc`; router `test_late_returns_bounds` |
| Q-42-4 non-UTC offset | router `test_late_returns_bounds` (real SQLite); service `test_offset_bound_is_converted_to_utc` |
| TC-42-06 single bound | repository `test_single_bound_applies_only_that_bound`; router `test_late_returns_bounds` |
| TC-42-07 `from > to` → 400 | service `test_from_after_to_raises_bad_request`; router `test_from_after_to_returns_400` |
| TC-42-08 / Q-42-3 invalid `from` / `to` → 422 | router `test_invalid_datetime_returns_422`; schema `test_invalid_value_fails_validation` |
| Q-42-5 invalid pagination → 422 | router `test_invalid_pagination_returns_422` (both endpoints) |
| TC-42-09 / TC-42-10 401 / 403 | router `test_no_token_returns_401`, `test_member_token_returns_403` |
| TC-42-11 one lookup per distinct user and book | service `TestPerPageLookupCache` (counting fakes; unit-only per Q-42-7) |
| TC-42-12 routes not shadowed | router `test_routes_are_not_shadowed_by_borrowing_id` |
| TC-42-13 existing overdue endpoints unchanged | router `test_existing_overdue_endpoints_are_unchanged` |
| TC-42-14 no envelope, `response_model` declared | router overdue test (page keys only); `test_openapi_declares_report_response_model` |
| TC-42-15 date-only `to` covers the whole UTC day | router `test_date_only_to_covers_the_whole_utc_day` (00:00Z and 23:59:59.999999Z in, next 00:00Z out, real SQLite); schema `test_date_only_means_end_of_that_day_utc` |
| TC-42-16 `to` with a time part stays literal | router `test_to_with_a_time_part_keeps_its_literal_meaning` (with and without `Z`); schema `test_explicit_midnight_is_unchanged` |
| TC-42-17 date-only `from` and `to` on the same day | router `test_date_only_from_and_to_on_the_same_day` |
| TC-42-18 `from` later the same day as a date-only `to` → 200 | router `test_from_later_the_same_day_as_date_only_to_is_valid` |
| Datetimes serialized with `Z`, not `+00:00` | router overdue and late-returns content tests |
| Missing user → `LookupError` | service `TestMissingReference` |

## Changes from plan

Added by the reviewer when approving the plan:

- `spec.md` is **not** edited in this PR; the spec will be updated separately. This drops the planned §10 row.
- No commit and no push. Stop after pytest, ruff, and mypy for a diff review.
- Do not run `ruff format .` or `pre-commit run --all-files`. Format only the changed `.py` files. `git status` must show no changed `.md` files. This plan file was added later, on request.
- Do not run `fastapi dev` or `seed_demo`. This drops the manual check from the plan's verification section.
- Router tests assert that datetimes in the response end with `Z`, not `+00:00`.
- The final report has a Decisions section: date-only `to` = end of day UTC (the new BA decision, replacing Dev Q2), and `LookupError` when a user or book is not found.

Found during implementation:

- `mypy` rejected comparisons on `Borrowing.returned_at` (`datetime | None`). The repository now wraps the column with `col()`.
- The `test_reports.py` helpers got type annotations (`FakeUserRepository` / `FakeBookRepository`) to fix `no-any-return`.
- Added `TestMissingReference` to cover the `LookupError` path, and `pageSize=101` / `page=abc` to the pagination 422 cases.
- The service-level Q-42-4 test runs on fakes, so Python compares the offset correctly with or without conversion. The real proof of `astimezone(UTC)` is the router test against SQLite.

After the spec update (PR #47, TC-42-15 – TC-42-18):

- `test_date_only_to_covers_the_whole_day` covered TC-42-15 – TC-42-17 only partly (one return at 18:00, no boundary rows) and TC-42-18 not at all. It is replaced by four router tests, one per case, using the matrix data. No app code changed: the `BeforeValidator` already turns a date-only `to` into the end of the day before the service compares `from > to`.
- Only `test_routers.py` changed, so ruff and mypy were also run on that file alone: both clean.
