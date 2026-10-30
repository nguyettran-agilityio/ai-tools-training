# Plan — #40 Ban a member from borrowing after a late return

Source: [#40](https://github.com/nguyettran-agilityio/ai-tools-training/issues/40) and its comments, [spec.md](spec.md), [test-matrix.md](test-matrix.md).
Status: approved plan, implemented on `feat/ban-on-late-return`. Migration `2445c20e0ab5` is generated and applied to the local SQLite database. Nothing is committed yet.

Decisions this plan relies on:

- **Q-40-1:** with `N = 0`, a late return still upserts the row with `banned_until = MAX(previous, returned_at)`. That row is never active.
- **Q-40-2:** `source_borrowing_id` changes only when `banned_until` moves later (strict `>`). An equal or earlier date leaves both values unchanged.
- **Q-40-3, superseded:** the latest BA comment on #40 says `updated_at` changes only when `banned_until` changes. `created_at` is always kept from the first insert.
- **Q-40-4 / Q-40-5:** the error order stays 404 → 403 → 409. An admin returning a member's loan also gets 403.
- **Q-40-6:** a repository-level test is enough for the concurrency AC.
- **Q-40-8b:** an active ban does not block deleting the user. The ban row is removed by FK cascade.

## Files that change

| File | Change |
|---|---|
| `app/core/config.py` | `late_return_ban_days: int = Field(default=7, ge=0)` under "Business rules" |
| `app/modules/borrowing/models.py` | New `BorrowingBan` table, described below |
| `app/core/model_registry.py` | Registers `BorrowingBan` |
| `app/modules/borrowing/schemas.py` | New `BorrowingBanRead`: `user_id`, `banned_until`, `source_borrowing_id`, `created_at`, `updated_at` |
| `app/modules/borrowing/mappers.py` | New `to_borrowing_ban_read`. It reuses `_as_utc` for all three datetimes |
| `app/modules/borrowing/repositories.py` | New `BorrowingBanUpdateFields` and `BorrowingBanRepositoryInterface` (`get_active_by_user`, `extend`, `list_active`) |
| `app/modules/borrowing/repositories_sqlmodel.py` | New `BorrowingBanRepository`. `extend` is one SQLite `INSERT ... ON CONFLICT(user_id) DO UPDATE` |
| `app/core/deps.py` | New `get_borrowing_ban_repository`. `get_borrowing_service` passes that repository and `settings.late_return_ban_days` |
| `app/modules/borrowing/services.py` | The `BorrowingService` constructor takes `borrowing_ban_repository` and `late_return_ban_days`. `return_book` calls `extend` when `now > due_date` |
| `tests/fakes.py` | New `FakeBorrowingBanRepository` with the same MAX, source and `updated_at` rules |
| `tests/modules/borrowing/test_services.py`, `test_notify_overdue.py` | Pass the two new constructor arguments |
| `tests/core/test_config.py`, `tests/modules/borrowing/test_repositories.py`, `test_routers.py`, `test_penalty.py` (new), `tests/modules/user/test_admin_routers.py` | New tests (see Proof) |
| `alembic/versions/2445c20e0ab5_add_borrowing_ban_table.py` | New migration (revises `25fd052b6468`). It creates `borrowing_ban` and `ix_borrowing_ban_banned_until`; `downgrade()` drops both |

The `BorrowingBan` table:

- `user_id`: PK, and FK to `user.id` with `ON DELETE CASCADE`.
- `banned_until`: NOT NULL, indexed.
- `source_borrowing_id`: nullable FK to `borrowing.id` with `ON DELETE SET NULL`.
- `created_at` and `updated_at`.

The upsert's `SET` clause, in the `extend` method of `repositories_sqlmodel.py`:

- `banned_until = MAX(old, excluded)`.
- `source_borrowing_id` and `updated_at` use `CASE WHEN excluded.banned_until > old.banned_until`.
- `created_at` is not in `SET`.

After the upsert, the row is read back with `populate_existing=True`.

## Order of work

1. Add the setting, model, registry entry, DTO and mapper.
2. Add the repository interface and the SQLModel implementation.
3. Wire `deps.py` and change `BorrowingService`.
4. Add the fake repository and fix the existing tests that build the service. Run the full suite as a regression check (338 passed).
5. Write the new tests. Run `pytest`, then `ruff format` and `ruff check` **on the changed `.py` files only**, then `mypy`.
6. Migration. The user runs `uv run alembic upgrade head`, because this worktree has no `library.db` yet. Then Claude runs `uv run alembic revision --autogenerate -m "Add borrowing_ban table"` and reviews the file:
   - It contains only `create_table("borrowing_ban")` and the `banned_until` index.
   - Both `ondelete` values are present.
   - `PrimaryKeyConstraint("user_id")` is present.
   - `down_revision = "25fd052b6468"`.
   - `downgrade()` reverses `upgrade()`.
   - There is no backfill.

   Then Claude runs ruff on that file only. The user runs `alembic upgrade head` again.
7. The user reviews the diff. Nothing is committed or pushed before that.

## Risks

- **SQLite-specific upsert (C-14).** `sqlite_insert` and the scalar `MAX(a, b)` only work on SQLite. They live only in `repositories_sqlmodel.py` and must be revisited if the database changes.
- **Datetime comparison in SQL.** SQLite stores `DateTime` as naive text, so `MAX` and `CASE` compare strings. This is correct only while every value is written by SQLAlchemy in the same format and in UTC. The service passes only UTC-aware values (`_now_utc()`, and `due_date` normalized by `to_borrowing_read`).
- **Stale identity map.** The upsert bypasses the ORM, so a `BorrowingBan` loaded earlier in the same session would be stale. `extend` re-reads the row with `populate_existing=True`.
- **Autogenerate against a missing or old database.** Without `library.db` at head, the generated revision would contain the whole schema. This is why step 6 starts with a human-run upgrade.
- **Spec drift.** spec §10 Q-40-3 and the ticket AC still say "`updated_at` is set to now" when a row is reused. The code follows the newer BA decision. The spec is intentionally not edited in this PR.
- **Concurrency is covered only by sequential, out-of-order calls** at repository level (Q-40-6). There is no multi-thread test.

## Proof

| Test-matrix case | Test |
|---|---|
| TC-40-01 | `tests/core/test_config.py::test_settings_load_with_defaults` |
| TC-40-02 | `tests/core/test_config.py::test_negative_late_return_ban_days_is_rejected` |
| TC-40-03, Q-40-1 | `tests/modules/borrowing/test_penalty.py::TestBanOnReturn::test_zero_ban_days_writes_a_row_that_is_never_active` |
| TC-40-04 | `test_penalty.py::TestBanOnReturn::test_return_before_due_date_creates_no_ban`, `test_routers.py::TestLateReturnBan::test_on_time_return_returns_200_and_creates_no_ban` |
| TC-40-05 | `test_penalty.py::TestBanOnReturn::test_return_exactly_at_due_date_is_on_time` |
| TC-40-06 | `test_penalty.py::TestBanOnReturn::test_return_one_second_late_bans_for_n_days`, `test_repositories.py::TestBorrowingBanRepository::test_extend_first_time_inserts_row`, `test_routers.py::TestLateReturnBan::test_late_return_returns_200_and_bans_the_member` |
| TC-40-07, Q-40-2 | `test_penalty.py::TestBanOnReturn::test_earlier_ending_late_return_leaves_the_ban_unchanged`, `test_repositories.py::TestBorrowingBanRepository::test_extend_with_earlier_or_equal_date_leaves_row_unchanged` (earlier and equal) |
| TC-40-08 | `test_penalty.py::TestBanOnReturn::test_later_late_return_moves_the_end_date_without_stacking`, `test_repositories.py::TestBorrowingBanRepository::test_extend_with_later_date_replaces_date_source_and_updated_at` |
| TC-40-09, new Q-40-3 rule | `test_repositories.py::TestBorrowingBanRepository::test_extend_reuses_expired_row_and_keeps_created_at` |
| TC-40-10 | `test_repositories.py::TestBorrowingBanRepository::test_extend_out_of_order_calls_keep_the_latest_date` |
| TC-40-11 | `test_routers.py::TestLateReturnBan::test_late_return_recorded_before_deploy_does_not_ban_returns_201` |
| TC-40-12 | `test_routers.py::TestLateReturnBan::test_late_return_returns_200_and_bans_the_member` |
| TC-40-13 | `test_penalty.py::TestBanOnReturn::test_late_return_sends_no_notification`, `test_routers.py::TestLateReturnBan::test_late_return_still_notifies_pending_reservers_returns_200` |
| TC-40-14 | `test_penalty.py::TestErrorPathsCreateNoBan::test_returning_someone_elses_late_loan_raises_forbidden`, `test_routers.py::TestLateReturnBan::test_someone_elses_late_loan_returns_403_and_creates_no_ban` |
| Admin 403 (Q-40-5) | `test_routers.py::TestLateReturnBan::test_admin_returning_a_members_late_loan_returns_403_and_creates_no_ban` |
| TC-40-15 | `test_penalty.py::TestErrorPathsCreateNoBan::test_returning_twice_raises_conflict_and_keeps_the_ban`, `test_routers.py::TestLateReturnBan::test_returning_a_late_loan_twice_returns_409_and_keeps_the_ban` |
| TC-40-16 | `test_repositories.py::TestBorrowingBanRepository::test_deleting_user_deletes_ban` |
| Q-40-8b | `tests/modules/user/test_admin_routers.py::TestDeleteUser::test_user_with_active_ban_and_only_returned_borrowing_returns_204` |
| TC-40-17 | `test_repositories.py::TestBorrowingBanRepository::test_deleting_source_borrowings_book_nulls_source` |
| TC-40-18 | `test_repositories.py::TestBorrowingBanRepository::test_datetimes_read_back_as_utc_aware` |
| Active boundary (`banned_until == now` is not active) | `test_repositories.py::TestBorrowingBanRepository::test_get_active_by_user_boundary` |
| `list_active` | `test_repositories.py::TestBorrowingBanRepository::test_list_active_excludes_expired_and_orders_soonest_first` |

Results on the implementation:

- `uv run pytest`: 367 passed.
- `ruff check` and `ruff format` on the changed files: clean.
- `uv run mypy`: no issues.

## Changes from plan

Added at plan review:

- Nothing is committed or pushed. Work stops after `pytest`, `ruff` and `mypy` so the user can review the diff.
- No `ruff format .` and no `pre-commit run --all-files`. Only the changed `.py` files are formatted. No existing `.md` file may change; this file is the only new one.
- Every datetime passed to `extend` or compared must be UTC-aware. `due_date` read from the repository is confirmed to be aware before it is compared with `now`.
- No `fastapi dev` and no `curl`. The plan's health-check step was dropped.
- The final report has a Decisions section:
  - `created_at` was added to `BorrowingBanRead` for internal use only.
  - `updated_at` follows the newer BA decision, which differs from Q-40-3 in the spec.

How the code differs from the plan:

- **Constructor order.** `borrowing_ban_repository` and `late_return_ban_days` are appended after `notifier`, so the existing positional order is unchanged. Tests pass them as keywords.
- **`on_conflict_do_update(index_elements=["user_id"])`** uses a string, not the column. mypy rejected the column object.
- **Router tests** are in a new class `TestLateReturnBan`, not added to `TestReturnBook`. A late loan is made by borrowing through the API and then moving `due_date` into the past in the database, instead of inserting the whole borrowing directly. This keeps `availableCopies` consistent.
- **TC-40-07 at service level** uses two services that share the same fakes: one with `ban_days=30`, one with `ban_days=7`. This produces an existing ban that ends later than the new one.
- **TC-40-11** is a router test only (the member still borrows with 201). There is no separate migration-time check, because the migration only creates an empty table.
- **The fake clock** is a `clock` fixture that monkeypatches `services._now_utc`.
- **Migration generated after the user's first upgrade.** The user ran `alembic upgrade head`, which created `library.db` at `25fd052b6468`. Claude then generated `2445c20e0ab5`; it passed every checklist item in step 6 with no hand edits. `ruff check --fix` changed `Union[...]` to `str | Sequence[str] | None` and moved the import to `collections.abc`. `ruff format` wrapped the `create_index` line. The user then ran the second upgrade, and the local database is at `2445c20e0ab5 (head)`.
- **Spec not edited.** At plan review the user decided not to update spec §10 Q-40-3 in this PR.
