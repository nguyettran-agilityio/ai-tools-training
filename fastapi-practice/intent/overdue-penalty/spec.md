# Overdue Penalty Policy — Requirements & Design Spec

Source intent: [intent.md](intent.md) (Status: Accepted)
Status: Accepted — all Lead decisions applied (OQ-1/2/3, C-1, C-2, C-3, C-4, C-6, C-7, C-8, C-10, C-12, C-17, C-20). Each decided item carries a "Resolved by Lead" note in place.
Constraints used: `CLAUDE.md` and the existing code patterns (`app/modules/category/` as the canonical layering, `app/modules/borrowing/` as the module being extended).

---

## 1. Summary

Add two new borrowing eligibility checks and an admin report:

1. **Late-return ban** — returning a loan after its `due_date` bans the member from borrowing for `N` days (default 7, configurable), counted from the return. A later late return during a ban moves the end date to the later of the two; bans never stack.
2. **Overdue-holding block** — a member holding at least one unreturned overdue loan cannot borrow.
3. **Overdue report** for admins (librarian = admin, OQ-3): currently overdue loans, late returns in a date range, currently banned members — each row showing the member's email and the book title.

Reservations are not affected, including the existing auto-reserve on an out-of-stock `POST /borrowings`. No fines, no retroactive bans, no proactive ban notifications.

---

## 2. Current behaviour (as found in code)

| Area | Where | Today |
|---|---|---|
| Overdue status | `BorrowingRead.status` (`app/modules/borrowing/schemas.py`) | Computed on read: `returned_at is None and due_date < now(UTC)`. Never stored. |
| Borrow checks | `BorrowingService.borrow` (`services.py`) | Order: book exists → borrow limit (`ConflictError`) → already borrowed (`AlreadyExistsError`) → atomic copy claim → if no copy, auto-create reservation and return `RESERVED` (router answers **202**). No overdue/ban check. |
| Return | `BorrowingService.return_book` | Only the owning member can return (`ForbiddenError` otherwise). Sets `returned_at = now(UTC)`. Router schedules `notify_book_available` in the background. |
| Renew | `BorrowingService.renew` | Already refuses overdue loans (`ConflictError("Overdue loans cannot be renewed")`). |
| Overdue list | `GET /borrowings/overdue`, `GET /borrowings?overdueOnly=true` (admin) | Paginated `Page[BorrowingRead]` of unreturned, past-due loans. |
| Reminders | `POST /borrowings/notify-overdue` (admin) | Sends `OVERDUE_REMINDER` via `CompositeNotifier`. |
| Roles | `UserRole` (`app/modules/user/enums.py`) | `member`, `admin` only. Admin check is `require_admin` in `core/deps.py`. |
| Business settings | `Settings` (`core/config.py`) | `borrow_limit`, `loan_duration_days`, `renewal_days`. Injected into `BorrowingService` by `get_borrowing_service`. |

---

## 3. Functional requirements

### FR-1 Late-return ban
- FR-1.1 A return is **late** when `returned_at > due_date` (strictly after; consistent with the existing overdue test `due_date < now`). No grace period.
- FR-1.2 On a late return, the member's ban end becomes `max(current_ban_end, returned_at + N days)`. If no ban exists, it is `returned_at + N days`.
- FR-1.3 `N` = `Settings.late_return_ban_days`, default `7`. Must be `>= 0`; `0` effectively disables the ban (see Concern C-9).
- FR-1.4 A member is **banned** at instant `t` when `ban_end > t`.
- FR-1.5 Only returns made after the feature is deployed count. Late returns that already exist in the database must never produce a ban (no backfill).
- FR-1.6 The ban is recorded when the return happens (inside `return_book`), not computed later from history (see §5.1 for the reasoning).

### FR-2 Overdue-holding block
- FR-2.1 A member with at least one loan where `returned_at is None and due_date < now` cannot borrow.
- FR-2.2 The block is computed on read (no stored flag), matching the "overdue is computed on read" rule in `CLAUDE.md`. It lifts automatically when the overdue loan is returned (and FR-1 may then start a ban).

### FR-3 Borrow refusal and messaging
- FR-3.1 When a borrow is refused because of a ban, the response tells the member the exact instant they can borrow again (`ban_end`, ISO 8601 UTC).
- FR-3.2 When refused because of an overdue holding, the response says which loan(s) must be returned first (borrowing id / book id).
- FR-3.3 No other notification (email, WebSocket) is sent for bans.

### FR-4 Reservations unaffected
- FR-4.1 `POST /reservations` performs no ban or overdue check.
- FR-4.2 Fulfilment is unchanged: a reservation is fulfilled only when its owner borrows the book — so a banned member who is notified that a reserved book is available still cannot borrow it until the ban ends (see Concern C-5).
- FR-4.3 `POST /borrowings` for a book with no available copy keeps its current behaviour for a banned member: the member is queued and gets **202** with the reservation, exactly as before. The ban only refuses a borrow that would actually hand out a copy. *Resolved by Lead (C-4): keep the intent; banned members are still auto-queued.*
- FR-4.4 The same applies to a member blocked by FR-2 (holding an overdue loan). *Resolved by Lead (C-20): confirmed.*

### FR-5 Overdue report (admin)
- FR-5.1 Currently overdue, unreturned loans.
- FR-5.2 Late returns, filterable by a `from`/`to` range on `returned_at`, paginated, newest first.
- FR-5.3 Currently banned members, with `bannedUntil`, paginated, soonest-ending first.
- FR-5.4 All report endpoints are admin-only (`require_admin`). *Resolved by Lead (OQ-3): librarian = admin.*
- FR-5.5 Every report row includes the member's email and the book title (for FR-5.3: the title of the book whose late return last set or extended the ban). *Resolved by Lead (C-10).*

### Non-functional
- NF-1 No background job, no scheduler (same as today).
- NF-2 All datetimes UTC-aware in services/schemas; SQLite naive values normalized in mappers (existing `_as_utc` pattern).
- NF-3 Concurrency: two simultaneous late returns by the same member must not lose the later end date (see §5.1 write rule).

---

## 4. Out of scope (from intent)

Monetary fines and payments; retroactive bans; proactive ban notifications by email or WebSocket.

- Member self-service view of ban status — *Resolved by Lead (OQ-1): out of scope.*
- Admin lift / manual creation of bans — *Resolved by Lead (OQ-2): deferred to a later feature.* The design keeps it possible (§5.1).
- A separate librarian role — *Resolved by Lead (OQ-3): librarian = admin.*

---

## 5. Design

### 5.1 Data model — store the ban, do not derive it

The intent leaves "derived from history vs recorded separately" to the spec. **Proposal: record it.**

*Resolved by Lead (C-1): Option B, a new `borrowing_ban` table. (C-2): changing `N` affects only future late returns; existing bans keep their end date.*

| Option | Pros | Cons |
|---|---|---|
| A. Derive from `borrowing` history (`max(returned_at) + N` over late returns) | No new table | Needs a "feature release" cutoff setting to satisfy FR-1.5; changing `N` silently changes every past and current ban; a ban can never be lifted or created by hand without adding storage anyway (violates the intent constraint). |
| **B. New `borrowing_ban` table (recommended)** | No cutoff hack: rows only exist for returns after deploy; `N` changes only affect new bans; lifting = update `banned_until`, manual ban = insert row; "banned members" report is a simple indexed query | One new table + migration + repository |
| C. `User.borrow_banned_until` column | Smallest change | Puts borrowing-domain state on the user model; `UserUpdateFields` is documented as "mirrors `UserUpdate` exactly" and would stop doing so; borrowing service would write through the user repository. |

**Option B table** (in `app/modules/borrowing/models.py`, next to `Borrowing`):

```
borrowing_ban
  user_id              UUID  PK, FK user.id ON DELETE CASCADE   -- one row per member
  banned_until         datetime  NOT NULL, indexed
  source_borrowing_id  UUID  NULL, FK borrowing.id ON DELETE SET NULL  -- the late return that last set/extended it
  updated_at           datetime  NOT NULL
  created_at           datetime  NOT NULL
```

- One row per member (upsert). An expired row (`banned_until <= now`) means "not banned"; it is reused on the next late return. No history of past bans is kept (the late-return report covers history).
- Write rule (NF-3): repository method performs an atomic upsert that keeps the later date, e.g. `INSERT ... ON CONFLICT(user_id) DO UPDATE SET banned_until = MAX(banned_until, excluded.banned_until)` in `repositories_sqlmodel.py`. No read-then-write in the service.
- Future OQ-2 support (deferred feature): an admin "lift" sets `banned_until = now`; a manual ban upserts with `source_borrowing_id = NULL`. Audit columns (`lifted_by`, `reason`) would be added then, not now.

DTO `BorrowingBanRead(CamelModel)`: `user_id`, `banned_until`, `source_borrowing_id`, `updated_at`. Mapper `to_borrowing_ban_read` normalizes UTC like `to_borrowing_read`.

Report DTOs (in `app/modules/borrowing/schemas.py`, C-10):

```python
class BorrowingReportRow(BorrowingRead):      # overdue + late-returns reports; keeps the computed `status`
    user_email: str
    book_title: str

class BannedMemberReportRow(CamelModel):
    user_id: uuid.UUID
    user_email: str
    banned_until: datetime
    source_borrowing_id: uuid.UUID | None
    source_book_title: str | None             # None if the source borrowing row is gone
```

`user_email` / `book_title` are non-null: `borrowing.user_id` and `book_id` are `ON DELETE CASCADE`, so a borrowing row never outlives its user or book.

### 5.2 Configuration
- `Settings.late_return_ban_days: int = 7` under "Business rules" in `core/config.py`. Read via `get_settings()`.
- `get_borrowing_service` passes it to `BorrowingService.__init__` as `late_return_ban_days`, same as `borrow_limit`.

### 5.3 Repository layer (`app/modules/borrowing/`)

New interface in `repositories.py` (no ORM imports), concrete in `repositories_sqlmodel.py`:

```python
class BorrowingBanUpdateFields(TypedDict, total=False):
    banned_until: datetime
    source_borrowing_id: uuid.UUID | None
    updated_at: datetime

class BorrowingBanRepositoryInterface(CrudRepositoryInterface[BorrowingBanRead, BorrowingBanUpdateFields]):
    def get_active_by_user(self, user_id, now) -> BorrowingBanRead | None: ...
    def extend(self, user_id, banned_until, source_borrowing_id, now) -> BorrowingBanRead: ...   # atomic MAX upsert
    def list_active(self, offset, limit, now) -> tuple[list[BorrowingBanRead], int]: ...
```

Additions to `BorrowingRepositoryInterface`:

```python
def list_overdue_by_user(self, user_id, now) -> list[BorrowingRead]: ...   # unreturned & due_date < now
def list_late_returns(self, offset, limit, returned_from, returned_to) -> tuple[list[BorrowingRead], int]: ...
```

- `list_late_returns` filters `returned_at IS NOT NULL AND returned_at > due_date`, plus optional range on `returned_at`, built with the existing `apply_filters` helper; ordered `returned_at DESC`.
- `deps.py` gets `get_borrowing_ban_repository` constructing `SQLModelBackend[BorrowingBan, BorrowingBanRead, BorrowingBanUpdateFields]` — the only place in the app that constructs a backend.
- `tests/fakes.py` gets `FakeBorrowingBanRepository` and the two new `FakeBorrowingRepository` methods.

`CrudRepositoryInterface.create()`'s generic path is not used for bans (the PK is `user_id`, not a generated `id`); see Concern C-11.

### 5.4 Service layer — `BorrowingService`

New constructor args: `borrowing_ban_repository: BorrowingBanRepositoryInterface`, `late_return_ban_days: int`.

**`borrow()` — new check order** (*revised after Lead decision on C-4*):

1. Book exists → `NotFoundError` (unchanged). Keep the returned `BookRead`.
2. Borrow limit → `ConflictError` (unchanged, same position as today)
3. Already borrowed this book → `AlreadyExistsError` (unchanged)
4. **Eligibility lookup, no raise yet:** active ban (`borrowing_ban_repository.get_active_by_user(user_id, now)`) and overdue loans (`borrowing_repository.list_overdue_by_user(user_id, now)`).
5. **If ineligible:**
   - 5a. Book has no available copy (`book.available_copies == 0`, from step 1) → auto-reserve exactly as today → `RESERVED` / **202**. Nothing is claimed.
   - 5b. Otherwise → raise `BorrowingBannedError` (409, with `bannedUntil`, FR-3.1); if not banned but holding an overdue loan → `OverdueLoanHeldError` (409, FR-3.2). Ban takes precedence when both apply.
6. **If eligible:** atomic claim (`try_decrement_available_copies`), else auto-reserve → `RESERVED` / 202 (unchanged).

Why the eligibility check cannot simply move after the claim: `try_decrement_available_copies` already takes a copy when it succeeds, so refusing afterwards would need a compensating increment. Peeking at `available_copies` (step 5a) avoids touching stock for an ineligible member. Race note in C-19.

A single `now = _now_utc()` is taken at the top of `borrow()` and used by the eligibility checks and `due_date`.

**`return_book()`:** after `mark_returned`, if `borrowing.returned_at > borrowing.due_date`, call `borrowing_ban_repository.extend(user_id, returned_at + timedelta(days=late_return_ban_days), borrowing.id, now)`. The return response stays `BorrowingRead` (no ban info in it — the intent asks only that the member is told on a refused borrow; OQ-1 resolved as out of scope). The copy increment and reservation notification are unchanged.

**`renew()`:** unchanged. A banned member may still renew a non-overdue loan (renewal is not a new borrow). *Resolved by Lead (C-6): agreed.*

**New report methods** (all return enriched rows, C-10):
- `report_overdue(pagination) -> Page[BorrowingReportRow]` — reuses `borrowing_repository.list_all(..., overdue_only=True, now)`.
- `report_late_returns(pagination, returned_from, returned_to) -> Page[BorrowingReportRow]`; raises `BadRequestError` if `returned_from > returned_to`.
- `report_banned(pagination) -> Page[BannedMemberReportRow]`.

Enrichment is done in the service with the repositories `BorrowingService` already holds (`user_repository`, `book_repository`), the same way `notify_overdue` resolves email and title today. Within one page, look up each distinct `user_id` / `book_id` once (small dict cache). Page size is capped at 100 by `PaginationParams`, so a page costs at most 200 extra lookups. Alternative in C-18.

`services.py` still imports nothing from `fastapi`.

### 5.5 Errors

Error body stays `{code, message, errors}` from the global handler; the status code is not repeated in the body.

| Case | Status | `code` | `message` | `errors` |
|---|---|---|---|---|
| Banned | 409 | `BORROWING_BANNED` | `You cannot borrow until 2026-11-05T10:00:00Z` | `[{"field": "bannedUntil", "message": "<ISO datetime>"}]` |
| Holding overdue loan | 409 | `OVERDUE_LOAN_HELD` | `Return your overdue book(s) before borrowing again` | `[{"field": "borrowingId", "message": "<uuid>"}, ...]` |
| Invalid date range | 400 | `BAD_REQUEST` | `'from' must be before 'to'` | — |

Exceptions are subclasses of `ConflictError` with their own `code`, so the global handler maps them with no change. They live in a new `app/modules/borrowing/exceptions.py` (no `fastapi` import). *Resolved by Lead (C-3): option (a).* `errors` reuses the existing `{field, message}` item shape from the validation handler so clients parse one format.

### 5.6 API

All new routes are static and declared in the "Static routes" block of `app/modules/borrowing/routers.py`, before `/{borrowing_id}` routes. Routers only: receive → call service → return; `response_model` declared; no envelope.

| Method & path | Auth | Query | Response | Notes |
|---|---|---|---|---|
| `GET /borrowings/reports/overdue` | admin | `page`, `pageSize` | `Page[BorrowingReportRow]` | New — report part 1 |
| `GET /borrowings/reports/late-returns` | admin | `from`, `to` (ISO datetime, optional), `page`, `pageSize` | `Page[BorrowingReportRow]` | New — report part 2 |
| `GET /borrowings/reports/bans` | admin | `page`, `pageSize` | `Page[BannedMemberReportRow]` | New — report part 3 (path name: see C-12) |
| `GET /borrowings/overdue` | admin | `page`, `pageSize` | `Page[BorrowingRead]` | **Existing, unchanged** (see C-17) |
| `POST /borrowings` | member | — | 201 / 202 / **409 new codes** | Changed behaviour; 202 still returned for an out-of-stock book even when banned; update the OpenAPI `responses` to document 409 |
| `POST /borrowings/{id}/return` | member | — | `BorrowingRead` | Side effect: may create/extend a ban |

Report rows include `userEmail` and `bookTitle` (`sourceBookTitle` for bans). *Resolved by Lead (C-10).*

None of the new endpoints are anonymous, so no rate limiting is required.

### 5.7 Migration
- One Alembic revision creating `borrowing_ban` (autogenerate after the model change, reviewed by hand, committed in the same PR as the model). The model must be registered in `core/model_registry.py` so autogenerate sees it.
- No data migration / backfill (FR-1.5).
- `alembic upgrade head` is run by a human, per `CLAUDE.md`.

### 5.8 Seed data
- `app/cli/seed_demo.py` should optionally create one late-returned loan and one active ban so the report is demoable. Nice-to-have, not required.

---

## 6. Testing plan

Mirrors `app/` under `tests/modules/borrowing/` (each dir has `__init__.py`).

| Level | File | Cases |
|---|---|---|
| Service (fakes, no DB) | `test_penalty.py` (new) | on-time return → no ban; 1 second late → ban `returned_at + N`; second late return during ban → later date wins, not summed; earlier-ending late return during ban → ban unchanged; ban expires exactly at `banned_until`; borrow while banned (copy available) → `BorrowingBannedError` with date, `available_copies` unchanged; borrow while holding overdue (copy available) → `OverdueLoanHeldError`; banned + holding overdue → ban error wins; limit reached + banned → limit error (C-20); banned + out of stock → `RESERVED`, reservation created, no copy claimed; holding overdue + out of stock → `RESERVED`; banned + out of stock + existing open reservation → existing reservation returned, no duplicate; renew while banned (non-overdue) → allowed; `late_return_ban_days=0` → no ban; report rows carry email and title, each user/book looked up once per page |
| Repository (in-memory SQLite) | `test_repositories.py` | `extend` keeps MAX under repeated calls; `list_active` excludes expired; `list_late_returns` range bounds inclusive/exclusive as specified; naive→UTC normalization |
| Router | `test_routers.py` | 409 body shape `{code, message, errors}` for both new codes; banned member + out-of-stock book → 202 with reservation body; report endpoints 401 (no token) / 403 (`member_token`) / 200 (`admin_token`) with `userEmail`/`bookTitle` in rows; `from > to` → 400; static routes not shadowed by `/{borrowing_id}`; existing `GET /borrowings/overdue` response unchanged |
| Reservation | `tests/modules/reservation/test_routers.py` | banned member can still `POST /reservations` → 201 |
| Settings | — | tests override `get_settings()` to set `late_return_ban_days` |

Time control: services take `now` from `_now_utc()`; tests should patch it or pass explicit timestamps to repositories (existing `now` parameter pattern in `list_all`).

---

## 7. Open questions (carried from intent)

**OQ-1 — Member self-view of ban status.**
Proposal: if yes, add `GET /borrowings/eligibility` (member, own data) returning `{canBorrow, bannedUntil, overdueBorrowingIds, activeCount, borrowLimit}`. Zero schema impact since §5.1 stores the ban. Until decided, the member only learns the date from a refused borrow (meets success criterion 1).
*Resolved by Lead: not built; out of scope for this feature. The member learns the ban end date only from a refused borrow (FR-3.1).*

**OQ-2 — Librarian intervention (lift early / create manually).**
The design keeps it possible (§5.1). Proposal: defer to a follow-up; if accepted, add `DELETE /borrowings/bans/{userId}` (lift = set `banned_until = now`) and `PUT /borrowings/bans/{userId}` (manual), plus audit columns `lifted_by` / `reason` in that follow-up migration.
*Resolved by Lead: deferred to a later feature. This feature must not block it (§5.1 storage keeps it possible).*

**OQ-3 — "Librarian" vs admin.**
Proposal: treat librarian = existing `admin` role for this feature (`require_admin`). A new role would touch `UserRole`, the DB enum (migration), `require_admin`, seed scripts and every admin-only endpoint — a separate feature.
*Resolved by Lead: librarian = admin. No new role.*

---

## 8. Areas of concern

Items marked **[LEAD]** need a decision; the others are risks or notes for the implementer. A **[LEAD]** item followed by a "Resolved by Lead" note is decided; the original text is kept for history. No item is still waiting on a Lead decision; the remaining unannotated items are implementation risks and notes.

- **C-1 [LEAD] Storage choice.** §5.1 recommends a new `borrowing_ban` table over deriving from history or a `User` column. Deriving would need a "release date" cutoff setting to satisfy "no retroactive bans", and would make `N` changes retroactive.
  *Resolved by Lead: agreed — new `borrowing_ban` table (Option B).*
- **C-2 [LEAD] Changing `N` later.** With stored bans, a new `N` affects only future late returns; existing bans keep their date. Confirm this is the intended meaning of "N is configurable".
  *Resolved by Lead: agreed — new `N` applies to future late returns only.*
- **C-3 [LEAD] Where the new exceptions live — conflicts with `CLAUDE.md`.** `CLAUDE.md` says services raise exceptions "from `core/exceptions.py`" *and* that `core/` is cross-module only with nothing domain-specific. `BorrowingBannedError` / `OverdueLoanHeldError` are domain-specific. Options: (a) put them in `app/modules/borrowing/exceptions.py` subclassing `ConflictError` (handler still works, but contradicts the first rule's wording); (b) put them in `core/exceptions.py` (contradicts the second rule); (c) raise plain `ConflictError` with the date in `message`/`errors` and accept `code = "CONFLICT"` (clients cannot tell ban vs limit vs overdue without parsing text). Spec assumes (a).
  *Resolved by Lead: agreed — option (a), `app/modules/borrowing/exceptions.py`, subclassing `ConflictError`.*
- **C-4 [LEAD] Ban vs auto-reserve on `POST /borrowings` — tension with "reservations are not affected".** Today an out-of-stock borrow auto-creates a reservation (202). With checks before the claim, a banned member gets 409 and is *not* auto-queued; they must use `POST /reservations`. The alternative (check after the claim fails) lets a banned member be auto-queued but gives inconsistent answers depending on stock. Spec picks "check first".
  *Resolved by Lead: keep the intent — a banned member borrowing an out-of-stock book is still auto-queued (202), as before. Check order revised in §5.4: book exists → limit → already borrowed → eligibility lookup → (ineligible: out of stock ⇒ auto-reserve 202, else 409) / (eligible: claim, else auto-reserve 202). Follow-on concerns: C-19, C-20.*
- **C-5 Banned member at the head of a reservation queue.** On return, every pending member is notified (`CompositeNotifier`), including banned ones who cannot borrow yet. Their reservation stays pending, others can borrow first. Matches FIFO rules but the notification may confuse banned members. No change proposed.
- **C-6 [LEAD] Renewal while banned.** Intent is silent. Spec allows renewing a non-overdue loan during a ban (renewal is not a new borrow; overdue renewals are already blocked).
  *Resolved by Lead: agreed — renewal allowed during a ban.*
- **C-7 "Days" definition.** Spec uses `returned_at + N × 24h` in UTC, not calendar days in a local timezone. "Counted from the day of the return" could be read as end-of-day local. Confirm.
  *Resolved by Lead: accepted — `returned_at + N × 24h` in UTC.*
- **C-8 Precision of "late".** `returned_at > due_date` means a return 1 second late triggers a 7-day ban. Intended ("any delay counts"), but worth a product sanity check and a clear message to members.
  *Resolved by Lead: accepted — any delay counts.*
- **C-9 `late_return_ban_days = 0`.** Spec treats it as "feature off" (ban end ≤ return time is never active). Validate `>= 0` in `Settings`.
- **C-10 Report content.** Existing overdue list returns ids only (`userId`, `bookId`). A librarian report is far more useful with member email/name and book title. Adding them means a new report DTO plus service-side joins via `user_repository` / `book_repository` (N+1 like `notify_overdue`) or a dedicated join query in the repository. Spec keeps ids only to match existing patterns.
  *Resolved by Lead: the report includes the member's email and the book title. Design in §5.1 (report DTOs), §5.4 (service-side enrichment) and §5.6 (`/borrowings/reports/*`). Follow-on concerns: C-17, C-18.*
- **C-11 Repository base contract.** `CrudRepositoryInterface` / `SQLModelBackend` assume a generated `id` PK. `borrowing_ban` keyed by `user_id` fits `get_by_id(user_id)` but `create()` would not be used; the upsert is a custom method. Alternative: give the table its own `id` PK plus a unique index on `user_id`. Implementer's call; affects the migration.
- **C-12 Route naming.** `GET /borrowings/reports/bans` (was `/borrowings/bans` in revision 1) is placed under borrowings because the ban is borrowing-domain state; a librarian might expect `GET /users?banned=true`. Putting it on `/users` would make the user module depend on borrowing data (`UserService` already depends on `BorrowingRepositoryInterface`, so it is possible). Pick one.
  *Resolved by Lead: keep `/borrowings/reports/...`.*
- **C-13 Admin cannot return on a member's behalf.** `return_book` is owner-only. In a real library the librarian records the return; then lateness is still measured at the moment of the API call. Not changed by this feature, but it means `returned_at` is when the member hit the endpoint.
- **C-14 SQLite and the atomic MAX upsert.** `ON CONFLICT ... DO UPDATE` with scalar `MAX(a, b)` works in SQLite; the code must stay inside `repositories_sqlmodel.py` (only file allowed to touch `sqlmodel`) and be revisited if the DB changes.
- **C-15 Existing late returns in demo/dev databases.** Because there is no backfill, members with past late returns are not banned after deploy, but they *do* appear in the late-returns report. This is intended (report ≠ ban) but may surprise reviewers.
- **C-16 Existing tests.** Adding `borrowing_ban_repository` and `late_return_ban_days` to `BorrowingService.__init__` breaks every place that constructs the service in tests (service unit tests and fakes). Also, existing tests that create overdue fixtures and then borrow again will start failing with `OVERDUE_LOAN_HELD` — expected, but they must be reviewed rather than blindly fixed.

*New in revision 2 (raised by the Lead decisions above; not yet decided):*

- **C-17 [LEAD] Existing `GET /borrowings/overdue` vs the new enriched overdue report.** Adding `userEmail`/`bookTitle` to the existing endpoint would change its response type (`Page[BorrowingRead]`), which `GET /borrowings?overdueOnly=true` also shares. Spec keeps it unchanged and adds `GET /borrowings/reports/overdue`, so there are now two admin overdue lists. Alternative: enrich the existing endpoint in place (additive fields, low break risk) and skip the new path; or deprecate `/overdue` later.
  *Resolved by Lead: keep the existing `/borrowings/overdue` unchanged; the overlap with `/borrowings/reports/overdue` is accepted.*
- **C-18 Enrichment cost and layering.** Service-side lookups (§5.4) are up to 200 single-row queries per page of 100. A single JOIN query would be faster, but it would make `borrowing/repositories_sqlmodel.py` import the `User` and `Book` table models from other modules; `CLAUDE.md` only says `repositories_sqlmodel.py` is the one file allowed to import table models, and does not say whether a module may import *another* module's model. Spec picks service-side lookups (same as `notify_overdue`). Revisit if report pages are slow.
- **C-19 Race in the out-of-stock peek (C-4 order).** Step 5a reads `available_copies` from the `BookRead` loaded at step 1. If a copy is returned or taken between that read and the response, an ineligible member may get 409 for a book that just ran out, or 202 for a book that just came back. Both outcomes are harmless (no copy is claimed in either case), and the existing 202 path already has a similar window. Accepted, not fixed.
- **C-20 [LEAD] Precedence and scope of the C-4 rule.** (a) The borrow limit stays *before* the ban check (its current position), so a banned member at the limit sees the limit error, not the ban date — and, as today, is not auto-queued. (b) The Lead decision covers banned members; spec applies the same auto-queue rule to members blocked for holding an overdue loan (FR-4.4) for consistency. Confirm both.
  *Resolved by Lead: (a) borrow limit before ban is OK; (b) the C-4 rule also applies to members holding an overdue loan (FR-4.4 kept).*

---

## 9. Acceptance criteria (mapped to intent success criteria)

1. After a late return, `POST /borrowings` for a book with an available copy returns 409 `BORROWING_BANNED` with `bannedUntil = returned_at + N days` until that instant, then succeeds. → SC-1
2. While holding an unreturned overdue loan, `POST /borrowings` for a book with an available copy returns 409 `OVERDUE_LOAN_HELD`. → SC-2
3. An admin can list currently overdue loans (`GET /borrowings/reports/overdue`), late returns in a range (`GET /borrowings/reports/late-returns`) and currently banned members (`GET /borrowings/reports/bans`); every row shows the member's email and the book title. → SC-3
4. A banned member can still create a reservation via `POST /reservations`, and `POST /borrowings` for an out-of-stock book still queues them with 202.
5. Late returns recorded before deployment never cause a ban.
