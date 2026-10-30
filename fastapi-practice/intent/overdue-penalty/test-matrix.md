# Overdue penalty — test matrix

Source: acceptance criteria in issues #39–#44 only. Code and `spec.md` were not consulted.

Conventions:

- `N` = `late_return_ban_days`. `D` = loan due date. `now` = server time at request.
- **Check via:** `API` = black-box HTTP call; `DB` = inspect the `borrowing_ban` / `borrowing` tables; `unit` = service/repository test with controlled time or fakes.
- Cases that need an exact instant (e.g. "exactly at `D`", "ban ends exactly at `now`") can only be run reliably at `unit` level with a frozen clock.
- **Priority:** High = core penalty rule, security, or exact error contract; Medium = secondary rule, boundary, regression; Low = docs, internals, optional demo data.

## #39 — Overdue penalty policy (epic, reviewer notes)

| ID | Ticket | Scenario | Preconditions | Steps | Expected | Check via | Priority |
|---|---|---|---|---|---|---|---|
| TC-39-01 | #39 | End-to-end: late return → ban → borrow refused → visible in reports | Member M with a loan past `D`; another book with a copy available; admin token | 1. M returns the late loan.<br>2. M calls `POST /borrowings` for the other book.<br>3. Admin calls `GET /borrowings/reports/bans` and `/reports/late-returns`. | 2: 409 `BORROWING_BANNED`.<br>3: M appears in both reports. | API | High |
| TC-39-02 | #39 (C-5) | Banned member is still notified when a reserved book becomes available | M banned; M has a pending reservation for book B (0 copies); another member holds B | 1. Holder returns B. | M receives the reservation notification (WebSocket + email) despite the ban. | API (WS) / unit | Medium |
| TC-39-03 | #39 (C-15) | Pre-deployment late returns are reported but never ban | DB contains a loan with `returned_at > due_date` recorded before the migration was applied | 1. Apply migration / deploy.<br>2. Check `borrowing_ban`.<br>3. Admin calls `GET /borrowings/reports/late-returns`. | 2: no ban row for that member.<br>3: the loan is listed. | DB + API | Medium |

## #40 — T1 Ban a member after a late return

| ID | Ticket | Scenario | Preconditions | Steps | Expected | Check via | Priority |
|---|---|---|---|---|---|---|---|
| TC-40-01 | #40 | Default ban duration | No override of `late_return_ban_days` | 1. Load settings. | `late_return_ban_days == 7`. | unit | Medium |
| TC-40-02 | #40 | Negative ban duration rejected | `late_return_ban_days = -1` | 1. Start the app / load settings. | Startup fails with a validation error. | unit | Medium |
| TC-40-03 | #40 | Zero ban duration → no active ban | `late_return_ban_days = 0`; member M with a loan past `D` | 1. M returns the loan.<br>2. Check for an active ban (`banned_until > now`). | No active ban for M. | unit / DB | Medium |
| TC-40-04 | #40 | Return before due date → no ban | M has a loan with `D` in the future | 1. `POST /borrowings/{id}/return`. | 200; no `borrowing_ban` row created or changed for M. | API + DB | High |
| TC-40-05 | #40 | Return exactly at `D` is on time | Frozen clock at `D` | 1. Return the loan at exactly `D`. | No ban created or changed. | unit | High |
| TC-40-06 | #40 | Return 1 second late creates a ban | Frozen clock at `D + 1s`; M has no ban | 1. Return the loan. | One `borrowing_ban` row for M: `banned_until = returned_at + N×24h` (UTC), `source_borrowing_id = loan id`. | unit + DB | High |
| TC-40-07 | #40 | Existing longer ban is not shortened | M banned until `T2`; late return where `returned_at + N < T2` | 1. Return the other loan late. | `banned_until` stays `T2`. | unit / DB | High |
| TC-40-08 | #40 | Existing shorter ban is extended, not stacked | M banned until `T1`; late return where `returned_at + N > T1` | 1. Return the other loan late. | `banned_until = returned_at + N` (not `T1 + N`). | unit / DB | High |
| TC-40-09 | #40 | Expired ban row is reused | M has a ban row with `banned_until` in the past | 1. M returns another loan late.<br>2. Count `borrowing_ban` rows for M. | Exactly one row for M, with the new `banned_until`. | DB | Medium |
| TC-40-10 | #40 | Concurrent late returns keep the later end date | M has two late loans | 1. Return both at the same time (concurrent requests or concurrent repository `extend` calls). | One row; `banned_until` = the later of the two end dates. | unit (repository) | Medium |
| TC-40-11 | #40 | No backfill for pre-deployment late returns | Late returns exist in DB before the migration | 1. Apply migration.<br>2. Inspect `borrowing_ban`. | No ban rows caused by those returns. | DB | Medium |
| TC-40-12 | #40 | Late return response and copy count unchanged | M has a late loan for book B | 1. Record `availableCopies` of B.<br>2. `POST /borrowings/{id}/return`. | Response is `BorrowingRead` with no ban field; B's `availableCopies` increased by 1. | API | High |
| TC-40-13 | #40 | Late return side effects | Book B has pending reservations; notifier observable | 1. M returns B late. | Reservation notification is sent; no ban email and no ban WebSocket message is sent. | unit (fake notifier) | Medium |
| TC-40-14 | #40 | Returning another member's loan | Loan L belongs to member A; member B is logged in; L is past `D` | 1. B calls `POST /borrowings/{L}/return`. | 403; no ban row created for A or B. | API + DB | High |
| TC-40-15 | #40 | Returning an already-returned loan | Loan already returned late; ban exists with `banned_until = X` | 1. Call return again. | Existing error behaviour (see Q-40-4); `banned_until` still `X`, no new row. | API + DB | Medium |
| TC-40-16 | #40 | User deletion cascades to the ban | M has a ban row; M can be deleted | 1. Delete M.<br>2. Inspect `borrowing_ban`. | M's ban row is gone. | DB | Medium |
| TC-40-17 | #40 | Source borrowing deletion nulls the reference | Ban row with `source_borrowing_id = L` | 1. Delete borrowing L (DB).<br>2. Inspect ban row. | Row remains; `source_borrowing_id IS NULL`. | DB | Low |
| TC-40-18 | #40 | Datetimes are UTC-aware on read | SQLite backend (stores naive datetimes) | 1. Create a ban.<br>2. Read it through the repository. | `banned_until`, `created_at`, `updated_at` are timezone-aware UTC. | unit (repository) | Medium |

## #41 — T2 Refuse borrowing for banned members / overdue holders

| ID | Ticket | Scenario | Preconditions | Steps | Expected | Check via | Priority |
|---|---|---|---|---|---|---|---|
| TC-41-01 | #41 | Banned member, copy available | M banned until `T`; book B has `availableCopies ≥ 1` | 1. M calls `POST /borrowings` for B.<br>2. Read B. | 409; body `code: "BORROWING_BANNED"`, `message: "You cannot borrow until <T ISO 8601 UTC>"`, `errors: [{field: "bannedUntil", message: "<T>"}]`; no status code in body; B's `availableCopies` unchanged. | API | High |
| TC-41-02 | #41 | Ban just expired | Frozen clock at `now == T` (and `now > T`) | 1. M borrows a book with a copy. | 201 as normal. | unit / API | High |
| TC-41-03 | #41 | Holding overdue loans, copy available | M not banned; M holds 2 unreturned loans with `due_date < now`; book B available | 1. M calls `POST /borrowings` for B.<br>2. Read B. | 409; `code: "OVERDUE_LOAN_HELD"`, `message: "Return your overdue book(s) before borrowing again"`, `errors` has exactly 2 items `{field: "borrowingId", message: "<uuid>"}`, one per overdue loan, no `bookId`; B unchanged. | API | High |
| TC-41-04 | #41 | Overdue block lifts after return (no ban) | `late_return_ban_days = 0`; M holds one overdue loan | 1. M returns the overdue loan.<br>2. M borrows a book with a copy. | 2: 201. | API | Medium |
| TC-41-05 | #41 | Returning the overdue loan triggers the ban | Default `N`; M holds one overdue loan | 1. M returns it.<br>2. M borrows a book with a copy. | 2: 409 `BORROWING_BANNED` (not `OVERDUE_LOAN_HELD`). | API | High |
| TC-41-06 | #41 | Another member's overdue loan does not block | Member A holds an overdue loan; member M has none and is not banned | 1. M borrows a book with a copy. | 201. | API | High |
| TC-41-07 | #41 | Banned and holding overdue → ban wins | M banned and holds an overdue loan | 1. M borrows a book with a copy. | 409 `BORROWING_BANNED`. | API | High |
| TC-41-08 | #41 | Banned + borrow limit reached → limit error | M banned; M holds 5 active loans | 1. M borrows another book (copy available, and separately one out of stock). | 409 `CONFLICT` (borrow limit), not `BORROWING_BANNED`; no reservation created. | API | High |
| TC-41-09 | #41 | Overdue holder + borrow limit reached → limit error | M holds 5 loans, at least one overdue; not banned | 1. M borrows another book. | 409 `CONFLICT` (borrow limit), not `OVERDUE_LOAN_HELD`. | API | Medium |
| TC-41-10 | #41 | Banned member borrows a book already held | M banned; M currently holds book B | 1. M borrows B again. | Existing `AlreadyExistsError` response. | API | Medium |
| TC-41-11 | #41 | Banned member, nonexistent book | M banned | 1. `POST /borrowings` with a random book id. | 404. | API | Medium |
| TC-41-12 | #41 | Banned member, out of stock → auto-reserve | M banned; book B `availableCopies == 0` | 1. M borrows B.<br>2. Read B. | 202 with a reservation as today; no copy claimed. | API | High |
| TC-41-13 | #41 | Overdue holder, out of stock → auto-reserve | M holds overdue loan; book B `availableCopies == 0` | 1. M borrows B. | 202 with a reservation; no copy claimed. | API | High |
| TC-41-14 | #41 | Ineligible member with existing open reservation | M banned (or overdue holder); M already has an open reservation for out-of-stock B | 1. M borrows B again.<br>2. List M's reservations. | Existing reservation returned; no duplicate. | API | Medium |
| TC-41-15 | #41 | Banned member can reserve directly | M banned | 1. `POST /reservations` for a book. | 201. | API | Medium |
| TC-41-16 | #41 | Banned member renews a non-overdue loan | M banned; M holds loan L not overdue | 1. `POST /borrowings/{L}/renew`. | Renewal succeeds. | API | Medium |
| TC-41-17 | #41 | Overdue loan renewal still refused | M holds overdue loan L | 1. `POST /borrowings/{L}/renew`. | Refused exactly as before this feature (see Q-41-3). | API | Medium |
| TC-41-18 | #41 | OpenAPI documents 409 | App running | 1. `GET /openapi.json`, inspect `POST /borrowings` responses. | 409 is documented. | API | Low |

## #42 — T3 Admin report: overdue loans and late returns

| ID | Ticket | Scenario | Preconditions | Steps | Expected | Check via | Priority |
|---|---|---|---|---|---|---|---|
| TC-42-01 | #42 | Overdue report content and order | Mix of: unreturned overdue loans (different `borrowedAt`), unreturned not-yet-due loans, returned loans | 1. Admin `GET /borrowings/reports/overdue?page=1&pageSize=20`. | 200 `Page[BorrowingReportRow]`; only unreturned loans with `due_date < now`; ordered `borrowedAt` desc; each row has all `BorrowingRead` fields incl. `status`, plus `userEmail` and `bookTitle`. | API | High |
| TC-42-02 | #42 | Overdue report pagination | More overdue loans than `pageSize` | 1. Request page 1 and page 2 with a small `pageSize`. | Pages do not overlap; `total` equals the full overdue count. | API | Medium |
| TC-42-03 | #42 | Late-returns content and order | Loans returned: before `D`, exactly at `D`, after `D` (several) | 1. Admin `GET /borrowings/reports/late-returns`. | Only `returned_at > due_date`; exactly-at-`D` excluded; ordered `returnedAt` desc; paginated; `userEmail` and `bookTitle` present. | API (+ unit for exact-`D`) | High |
| TC-42-04 | #42 | Inclusive `from` / `to` bounds | Late returns at `t1 < t2 < t3` | 1. Call with `from=t1&to=t3`.<br>2. Call with `from=t2&to=t2`. | 1: all three. 2: only `t2`. | API / unit | High |
| TC-42-05 | #42 | Naive datetime treated as UTC | Late return at `2026-11-01T00:00:00Z` | 1. Call with `from=2026-11-01T00:00:00` (no tz). | The loan is included (interpreted as UTC). | API / unit | Medium |
| TC-42-06 | #42 | Single bound | Late returns before and after `t` | 1. Call with only `from=t`.<br>2. Call with only `to=t`. | 1: only `returnedAt >= t`. 2: only `returnedAt <= t`. | API | Medium |
| TC-42-07 | #42 | `from > to` | — | 1. Call with `from` later than `to`. | 400; `code: "BAD_REQUEST"`, `message: "'from' must be before 'to'"`. | API | High |
| TC-42-08 | #42 | Invalid datetime | — | 1. Call with `from=not-a-date`. | 422 from the existing validation handler. | API | Medium |
| TC-42-09 | #42 | No token | — | 1. Call both endpoints without a token. | 401 for both. | API | High |
| TC-42-10 | #42 | Member token | `member_token` | 1. Call both endpoints. | 403 for both. | API | High |
| TC-42-11 | #42 | One lookup per distinct user/book per page | Page with several rows sharing users/books | 1. Call service report methods with counting fakes. | Each distinct user and book is fetched once. | unit | Low |
| TC-42-12 | #42 | Routes not shadowed by `/{borrowing_id}` | Admin token | 1. Call both report URLs. | Report response (200 page), not a borrowing-by-id 404/422. | API | Medium |
| TC-42-13 | #42 | Existing overdue endpoints unchanged | Overdue loans exist | 1. `GET /borrowings/overdue`.<br>2. `GET /borrowings?overdueOnly=true`. | Same status, shape and content as before this feature (regression). | API | Medium |
| TC-42-14 | #42 | No envelope; `response_model` declared | — | 1. Inspect report response body.<br>2. Inspect OpenAPI for both routes. | Body is the page object directly; OpenAPI shows the response schema. | API | Low |
| TC-42-15 | #42 (B-42-2) | Date-only `to` covers the whole UTC day | Late returns at `2026-11-01T00:00:00Z`, `2026-11-01T23:59:59.999999Z`, `2026-11-02T00:00:00Z` | 1. Call with `to=2026-11-01`. | The two Nov 1 returns are included; `2026-11-02T00:00:00Z` is excluded. | API / unit | High |
| TC-42-16 | #42 (B-42-2) | `to` with a time part keeps its literal meaning | Late returns at `2026-11-01T00:00:00Z` and `2026-11-01T10:00:00Z` | 1. Call with `to=2026-11-01T00:00:00Z`.<br>2. Call with `to=2026-11-01T00:00:00` (no tz). | Both calls: only the `00:00:00Z` return is included. | API / unit | Medium |
| TC-42-17 | #42 (B-42-2) | Date-only `from` and `to` on the same day | Late returns at `2026-10-31T23:59:59Z`, `2026-11-01T12:00:00Z`, `2026-11-02T00:00:00Z` | 1. Call with `from=2026-11-01&to=2026-11-01`. | Only the `2026-11-01T12:00:00Z` return is included. | API | Medium |
| TC-42-18 | #42 (B-42-2) | `from` later on the same day as a date-only `to` is not `from > to` | Late returns at `2026-11-01T10:00:00Z` and `2026-11-01T18:00:00Z` | 1. Call with `from=2026-11-01T12:00:00Z&to=2026-11-01`. | 200 (not 400 `BAD_REQUEST`); only the `18:00:00Z` return is included. | API | Medium |

## #43 — T4 Admin report: banned members

| ID | Ticket | Scenario | Preconditions | Steps | Expected | Check via | Priority |
|---|---|---|---|---|---|---|---|
| TC-43-01 | #43 | Active bans only, soonest-ending first | Bans ending at different future times, plus one expired ban | 1. Admin `GET /borrowings/reports/bans?page=1&pageSize=20`. | 200 `Page[BannedMemberReportRow]`; expired ban excluded; ordered by `bannedUntil` asc. | API | High |
| TC-43-02 | #43 | Row fields | One active ban from a late return of book B | 1. Call the report. | Row has `userId`, `userEmail`, `bannedUntil` (UTC), `sourceBorrowingId`, `sourceBookTitle` = title of B (the late return that last set/extended the ban). | API | High |
| TC-43-03 | #43 | Ban ending exactly at `now` excluded | Frozen clock; ban with `banned_until == now` | 1. Call `report_banned`. | Not included. | unit | Medium |
| TC-43-04 | #43 | Source borrowing deleted | Ban row with `source_borrowing_id = NULL` | 1. Call the report. | Row returned with `sourceBorrowingId = null`, `sourceBookTitle = null`. | API + DB | Medium |
| TC-43-05 | #43 | No bans | No active bans | 1. Call the report. | 200; `items = []`, `total = 0`. | API | Medium |
| TC-43-06 | #43 | Auth | — | 1. Call without token.<br>2. Call with `member_token`. | 1: 401. 2: 403. | API | High |
| TC-43-07 | #43 | One lookup per distinct user/book per page | Several bans sharing a source book | 1. Call service with counting fakes. | Each distinct user and book fetched once. | unit | Low |
| TC-43-08 | #43 | Route not shadowed by `/{borrowing_id}` | Admin token | 1. `GET /borrowings/reports/bans`. | Report response, not a borrowing-by-id response. | API | Medium |

## #44 — T5 (optional) Seed demo data

| ID | Ticket | Scenario | Preconditions | Steps | Expected | Check via | Priority |
|---|---|---|---|---|---|---|---|
| TC-44-01 | #44 | Seed creates penalty data | Migrated database | 1. `uv run python -m app.cli.seed_demo --force`.<br>2. Inspect DB. | ≥1 late-returned loan, ≥1 unreturned overdue loan, ≥1 `borrowing_ban` row with future `banned_until`. | DB | Medium |
| TC-44-02 | #44 | All three reports non-empty | Seeded DB; admin token | 1. Call `/reports/overdue`, `/reports/late-returns`, `/reports/bans`. | Each returns ≥1 row. | API | Medium |
| TC-44-03 | #44 | Banned demo member refused | Seeded DB; logged in as the banned demo member | 1. Borrow a book with a copy available. | 409 `BORROWING_BANNED`. | API | Medium |
| TC-44-04 | #44 | Seed is re-runnable | Migrated database | 1. Run the seed with `--force` twice. | No error on the second run. | API (CLI) | Low |

## Questions for BA

### #39

- **Q-39-1** — C-5 says a banned member is still notified when a reserved book becomes available, but #39 does not say which channels. Is it the same as any other member (WebSocket and email)? TC-39-02 cannot set a precise expected result without this.

### #40

- **Q-40-1** — With `late_return_ban_days = 0`, the AC only says "no active ban results". Should a `borrowing_ban` row be created or updated (with `banned_until = returned_at`), or should no row be written at all? A DB-level check cannot be written until this is decided.
- **Q-40-2** — When a late return does **not** extend the ban (`returned_at + N < T2`), does `source_borrowing_id` stay the old loan or change to the new one? And what if `returned_at + N == T2` exactly? This also decides `sourceBookTitle` in #43.
- **Q-40-3** — When an expired ban row is reused, should `created_at` be kept or reset? The AC defines `banned_until` only.
- **Q-40-4** — "Given a loan that has already been returned, the existing error behaviour is unchanged." The ticket does not state what that behaviour is (status code and `code`). QA needs the expected status and body to write TC-40-15 without reading code.
- **Q-40-5** — The 403 for returning someone else's loan: what is the error body `code`? Does an **admin** returning a member's loan also get 403? Non-scope says admins cannot return on a member's behalf, but no AC covers it.
- **Q-40-6** — "Two late returns by the same member at the same time" cannot be reproduced reliably as a black-box API test. Is a repository-level concurrency test enough to accept this AC, or does QA need an API-level test?
- **Q-40-7** — "Late returns recorded before this feature is deployed": how should QA create this state in a test environment (e.g. insert rows before running the migration)? Is that the expected procedure?
- **Q-40-8** — User deletion cascade: business rules say deleting a user with active borrowings or open reservations returns 409. Should QA test cascade with a member who has only returned loans and a ban? Should an **active ban** itself block deleting the user?
- **Q-40-9** — There is no API to delete a borrowing in these tickets. Is `source_borrowing_id → NULL` testable only by deleting the row in the DB directly? When can this happen in production?

### #41

- **Q-41-1** — Exact format of `<T in ISO 8601 UTC>` in `message` and `errors[0].message`: `Z` or `+00:00`? Are fractional seconds included? An exact-match assertion needs this.
- **Q-41-2** — When several overdue loans are listed in `errors`, is there a required order (e.g. by due date)? If not, should QA compare them as an unordered set?
- **Q-41-3** — "An overdue loan is still refused as before" (renewal) and "the existing borrow-limit 409 `CONFLICT`": the tickets do not state the current status/body. Please give the expected response so the regression cases are not based on reading code.
- **Q-41-4** — "Given the member returns the overdue loan, then the overdue block lifts immediately. If that return was late, the ban from #40 applies instead." An overdue loan's return is always late, so with the default `N` the ban always applies. Is the "block lifts" part only observable with `late_return_ban_days = 0`? Is that the intended way to verify it?
- **Q-41-5** — Borrow limit vs. eligibility: when the member is banned, at the borrow limit, and the book is out of stock, the AC says "no auto-reserve". Should the response be the borrow-limit 409, and is this different from today's behaviour for a non-banned member at the limit with an out-of-stock book?
- **Q-41-6** — Is a loan with `due_date == now` exactly considered overdue for the block? The AC says `due_date < now` (so not overdue); please confirm this is intended, since #40 treats a return at `D` as on time.

### #42

- **Q-42-1** — Late-returns report rows may belong to a user or book that has since been deleted (returned loans do not block deletion). What should `userEmail` / `bookTitle` be then (null, row omitted, or error)?
- **Q-42-2** — 400 for `from > to`: what is the expected `errors` value (empty list, or a field entry)?
- **Q-42-3** — 422 is specified only for an invalid `from`. Should an invalid `to` also return 422?
- **Q-42-4** — Are datetimes with a non-UTC offset (e.g. `+07:00`) accepted and converted to UTC? Only the no-timezone case is specified.
- **Q-42-5** — No default or maximum for `page` / `pageSize` is stated for the report endpoints. Are they the same as the existing paginated endpoints? What should invalid values (e.g. `pageSize=0`) return?
- **Q-42-6** — Ordering ties: two rows with the same `borrowedAt` (overdue report) or same `returnedAt` (late-returns report). Is a secondary sort order required, or is any order acceptable?
- **Q-42-7** — "Each distinct user and book is looked up only once per page" is an implementation detail and cannot be verified through the API. Is a unit test with call-counting fakes acceptable as the acceptance evidence?

### #43

- **Q-43-1** — If the source borrowing still exists but its book has been deleted, what is `sourceBookTitle`?
- **Q-43-2** — Ordering ties when two bans have the same `bannedUntil`: is a secondary order required?
- **Q-43-3** — Same as Q-42-7 for the "looked up only once per page" AC.

### #44

- **Q-44-1** — Which demo account is the banned member, and what are its login credentials? The ticket does not say, so TC-44-03 cannot be run without this.
- **Q-44-2** — How long is the seeded ban? If the seed sets a ban of `N` days, the "bans report returns at least one row" AC fails if the demo runs more than `N` days after seeding. Is that acceptable?
- **Q-44-3** — "Run twice with `--force` does not raise an error": after the second run, must the AC-1 data (late return, overdue loan, future ban) still exist, and with no duplicates?
