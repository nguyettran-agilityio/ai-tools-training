# Day 2 – Ticket analysis, reproduce and understand

## Part 1 – Ticket analysis

**The three prompts** (each run in a new chat)

v1 (typed as a quick question, with the typo):

```
Please help me analysis this ticket: [ticket]
```

v2 adds a role, "use ONLY the ticket text", a fixed 3-sentence format and questions for the reporter:

```
I'm a developer analyzing a ticket before starting work. Use ONLY the ticket text below; do not assume anything not written.
Answer in exactly 3 numbered sentences:
1. What the ticket asks for.
2. What is ambiguous or missing.
3. The first step I should take.
Then list up to 5 clarifying questions for the reporter, ordered by which one blocks work the most. Mark any assumption you make.
Ticket: [ticket]
```

v3 is v2 plus three things: a `<context>` block (app, modules, roles), a line "Type: bug / feature request / possibly by design", and "write the questions in plain language". I ran v3 only on tickets 1, 4 and 5.

**v1 vs v2 on the 5 tickets**

| Ticket                               | v1                                                                                                                                      | v2                                                                                                                                                         | v2 is better because                                                        |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| 1 Notify overdue (business rule)     | Listed likely causes and sample code as facts, with names that are not in my app (`Loan`, `returned_at`). Asked the reporter nothing.   | 3 short sentences and 5 questions: which account and book, the exact message, how the book was returned, what "very long time" means, sent more than once. | No made-up causes. It asks the reporter instead of guessing.                |
| 2 Cancel reservation (bug)           | Decided that "available" means a READY state. Wrote code for a route that does not exist (`POST /reservations/{id}/cancel`).            | Said "what does available mean?" and "is cancelling allowed?" are missing, and asked both. Marked its one assumption.                                      | It asks when a word has two meanings instead of picking one.                |
| 3 Delete category (related data)     | Picked a rule by itself (block the delete with 409). Wrote a fix, SQL and tests. Its only question was for the developer.               | Asked what the rule should be (block, move the books or allow no category), what to do with books already without a category, and how the page fails.      | It asks for the missing rule first. Its first step is an action in the app. |
| 4 Search by author (feature request) | Wrote a full requirements document (under 1 second, 300 ms debounce, API route, code). Decided that "easier" means a search box.        | Asked what "easier" means (search box, filter or sort), which screen, and how the name is typed. Saw that the title already says "search".                 | It does not choose the solution for the reporter.                           |
| 5 Member sees all users (permission) | Said "yes, a real problem" and believed the friend. Added OWASP, GDPR, a severity rating, a guessed address (`/admin/users`) and a fix. | Did not trust the claim yet. Asked how the list was reached, which fields were shown, and who can confirm the rule.                                        | It checks the rule before judging.                                          |

It is the same every time: v1 fills the gaps itself with causes, code and a fix. v2 uses only the ticket and asks questions.

v3 (run on tickets 1, 4 and 5 only) was close to v2. It helped most on ticket 4: the type line was correct, the questions were plainer ("is there a search box today?"), and the first step included a check in the app. I did not test the lines one by one, so I am not sure which line did it.

**Role-play (ticket 5, Claude as the reporter)**

- Best question: "step by step for this bug". It gave the whole path: `/docs`, "users", "Try it out", "Execute".
- My mistakes: I asked the same question twice, and "when you reload have page show?" was unclear. I forgot to ask if the reporter logged in on the `/docs` page.
- Questions I would send:
  1. On that page, did you type your username and password (a button may say "Authorize") before pressing "Execute"?
  2. Which line did you press "Try it out" on? Please copy it or send a screenshot.
  3. When did you do this, and can you see the same list now?

## Part 2 – Reproduce the bug

- Bug ticket: Ticket 2, Cancel reservation (branch `practice/seed-bug`)
- Seeded bug: written in a file outside the repo, so it was never in a prompt. The cause is in "Real cause" below.
- Setup: `cp .env.example .env`, `uv sync`, `uv run pytest` (313 passed)
- Stack trace: `app.core.exceptions.ConflictError: Reservation is already fulfilled or cancelled`, raised in `cancel()` at `app/modules/reservation/services.py:65`

**Bug report** (reproduce-ready)

Title: Cancelling a NOTIFIED reservation raises ConflictError

Steps to reproduce:

1. On branch `practice/seed-bug`, from `fastapi-practice`, run `uv run pytest tests/modules/reservation/test_services.py -k notified -q`.
2. The test creates a reservation, sets it to `NOTIFIED`, then cancels it as its owner.
3. In Swagger (`/docs`), the same case is `DELETE /reservations/{reservation_id}` on a reservation that is `NOTIFIED`.

The test, in `tests/modules/reservation/test_services.py`, class `TestCancel`:

```python
def test_cancels_a_notified_reservation(self, service, book_repository):
    book = _make_book(book_repository)
    user_id = uuid.uuid4()
    reservation = service.create(user_id, ReservationCreate(book_id=book.id))
    service.reservation_repository.mark_notified(reservation.id, datetime.now(UTC))

    service.cancel(user_id, reservation.id)

    assert reservation_status(service, reservation.id) == "cancelled"
```

It sets `NOTIFIED` with `mark_notified`, the same repository method that `notify_book_available` uses.

Expected: `cancel()` returns `None` and the reservation status is `cancelled`. The expectation comes from the docstring of `cancel()`: "409s if it's already fulfilled or cancelled". A `NOTIFIED` reservation is neither. No other side effect is expected: `cancel()` only calls `mark_cancelled`.

Actual: the test fails on every run, and also when I run the whole `TestCancel` class:

```
tests/modules/reservation/test_services.py:110: service.cancel(user_id, reservation.id)
app/modules/reservation/services.py:65: raise ConflictError("Reservation is already fulfilled or cancelled")
FAILED ...::test_cancels_a_notified_reservation - ConflictError: Reservation is already fulfilled or cancelled
1 failed, 1 passed, 9 deselected
```

The 4 other `TestCancel` tests pass.

Environment: macOS, Python 3.12.12, uv, FastAPI 0.141.1, pytest 9.1.1, pydantic 2.13.4, repository `nguyettran-agilityio/ai-tools-training`, branch `practice/seed-bug`, commit `91d9aa1`, in-memory fake repositories (service-level test, no database).

Impact: a member who was told "your book is available" would not be able to cancel the reservation.

Hypotheses. v1 was "Fix this error for me". v2 was "give me 3 hypotheses and one check for each, do not fix anything".

- v1: it said it could not see `services.py`, guessed that the guard in `cancel()` is too strict, and wrote two fixes. It gave no command to run.
- v2: 3 hypotheses in order, each with a reason and a check I can run. It did not fix anything.
- The inputs were not the same size: v2 got the full traceback with the code of `cancel()`, v1 said it could not see the file. So this comparison is not fair on who found the cause.

The exact prompts and answers are in the appendix at the end.

| Hypothesis                                                                             | From                     | How I checked                                                                                                                     | Result    |
| -------------------------------------------------------------------------------------- | ------------------------ | --------------------------------------------------------------------------------------------------------------------------------- | --------- |
| The guard in `cancel()` only allows `PENDING`, so a `NOTIFIED` reservation is rejected | v2 (v1 guessed the same) | Removed my change with `git stash`, ran the test: 2 passed. Ran `-k TestCancel`: only the notified test fails, the 4 others pass. | Confirmed |
| `mark_notified` in the fake repository does not set the status to `NOTIFIED`           | v2                       | `grep -A8 "def mark_notified" tests/fakes.py`: it sets `status` to `NOTIFIED`                                                     | Rejected  |
| The rule changed on purpose, so the test is out of date                                | v2                       | `git log --oneline` on `services.py`: only the first commit, "Add FastAPI practice app"                                           | Rejected  |

One command from v2 did not fit at that time: my change was not committed yet, so `git log -p -S...` found nothing. I used `git log` on the file instead.

Real cause: in `cancel()` in `services.py`, the allowed statuses are `(PENDING,)`. `NOTIFIED` is missing, so a user who was told "your book is available" cannot cancel.

Which line of v2 made the difference: "For each: why you think so, and one command or check I can run to confirm or reject it". It turned the answer into a list I could test. v1 gave a guess and a fix.

## Part 3 – Failing test

```python
def test_cancels_a_notified_reservation(self, service, book_repository):
    book = _make_book(book_repository)
    user_id = uuid.uuid4()
    reservation = service.create(user_id, ReservationCreate(book_id=book.id))
    service.reservation_repository.mark_notified(reservation.id, datetime.now(UTC))

    service.cancel(user_id, reservation.id)

    assert reservation_status(service, reservation.id) == "cancelled"
```

Fails for the right reason? Yes. It fails with `ConflictError` from `cancel()`, not from the `assert`.

My first version never set the reservation to `NOTIFIED`, and it asserted the wrong status (`"notified"`). Claude pointed out both problems and gave the fixed version. The final version above is the one Claude gave me, because I asked for the code after I got stuck. The exercise says the dev writes the test, so this part is only half mine.

## Summary

- What I checked myself: I know the real app, so I spotted the invented routes (`POST /reservations/{id}/cancel`, `/admin/users`).
- Prompts I will reuse: "use ONLY the text I give", "mark every assumption", a fixed format, questions ordered by what blocks work, plain language for non-technical readers.
- Reproduce-ready report: steps to reproduce, expected vs actual, environment. I checked it by asking Claude to read it as a developer who knows nothing about the issue.
- Part 2: the line "one check I can run for each" turned the answer into a list I could test.
- Lesson learned: telling Claude to use only the ticket and mark assumptions changed the most. Without it, Claude fills the gaps itself with a cause and a fix.

## Appendix – Tickets

For each ticket: the text and the gaps it leaves out.

**Ticket 1: Notify overdue**

- Ticket: "Hi, I got a message saying my book is overdue, but I returned it last week. Also the message says I have been late for a very long time, which is not true. Please fix."
- Gaps left: how the book was returned, how the message arrived, the number of days it showed vs the real number.

**Ticket 2: Cancel reservation**

- Ticket: "I tried to cancel my reservation for a book that is already available. The app showed an error and the reservation is still there."
- Gaps left: what "available" means, whether cancelling is allowed in that state, the exact error message.

**Ticket 3: Delete category**

- Ticket: "An admin deleted a category that still has books. Now those books have no category and the book list page fails to load."
- Gaps left: the rule for deleting a category with books, what "fails to load" looks like, what to do with books that already lost their category.

**Ticket 4: Search books by author**

- Title: "search book my author". Ticket: "I work at the front desk and members often ask me for books by a specific writer. Right now I have to scroll through the whole list, which takes a long time when the library is busy. Could we make it easier to find books by writer? It would really help us during peak hours."
- Gaps left: what "easier" means (search box, filter or sort), who uses it and on which screen, how the author name is typed. The title already gives away "search".

**Ticket 5: Member sees all users**

- Ticket: "I logged in with my normal member account (not the librarian one) and I was able to see the full list of users, including names and emails of other members. My friend says this should only be visible to librarians. Is this a problem? I'm not sure how I got to that list, I think I tried something in the browser."
- Gaps left: how the list was reached, which fields were shown, whether "librarians only" is the real rule.

## Appendix – Part 2: exact prompts and answers

**Prompt v1** (the pasted parts are shortened)

```
Fix this error for me:
[pytest error and my test]
```

**v1 answer**

````markdown
I can't see `services.py`, so this is an educated guess. The message says "already fulfilled or cancelled," but your test's reservation is only notified. That points to a guard in `cancel()` that is too strict. It probably only allows `pending` instead of rejecting just the terminal states.
Line 65 likely looks something like this:
python

```python
# likely current (too strict)
if reservation.status != ReservationStatus.PENDING:
    raise ConflictError("Reservation is already fulfilled or cancelled")
```

The fix is to block only terminal states, so both pending and notified reservations can be cancelled:
python

```python
if reservation.status in (ReservationStatus.FULFILLED, ReservationStatus.CANCELLED):
    raise ConflictError("Reservation is already fulfilled or cancelled")
```

Or, if you prefer an allow-list:
python

```python
CANCELLABLE = {ReservationStatus.PENDING, ReservationStatus.NOTIFIED}

if reservation.status not in CANCELLABLE:
    raise ConflictError("Reservation is already fulfilled or cancelled")
```

Some things to check:

- Enum names: use whatever your status enum or constants are actually called.
- Test setup: make sure `mark_notified` sets the status to `"notified"`. If it only sets a `notified_at` timestamp and leaves the status as `pending`, the guard isn't the problem. Something else in `cancel()` (such as a check on `notified_at`) would be.
- Side effects: if a notified reservation held a copy of the book for the user, cancelling it may need to release that copy or notify the next person in the queue. Check whether `cancel()` already handles that for the pending case.

If you paste `cancel()` and the status enum or constants, I can give you the exact fix instead of a guess.
````

**Prompt v2** (the pasted parts are shortened)

```
Here is a stack trace and the relevant code from a FastAPI app. Do not fix anything yet.
Give me 3 hypotheses for the cause, most likely first. For each: why you think so, and one command or check I can run to confirm or reject it.
<stack trace>
[pytest traceback]
</stack trace>
<code>
[my test and cancel()]
</code>
```

**v2 answer**

```markdown
Hypothesis 1 (most likely): the guard in `cancel()` only allows `PENDING`, so a `NOTIFIED` reservation is rejected.
The condition is `status not in (ReservationStatus.PENDING,)`, with a tuple that has a single element and a trailing comma. That looks like a tuple that used to hold more statuses (probably `NOTIFIED` too) and was trimmed, or was never finished. The test marks the reservation as notified and then expects cancel to work, so the service and the test disagree about whether `NOTIFIED` is cancellable. The docstring says it 409s only when "already fulfilled or cancelled", which doesn't mention notified, so the code looks like the odd one out.
Check: `git log -p -S"ReservationStatus.PENDING," -- app/modules/reservation/services.py` to see whether that tuple was recently narrowed. Also `grep -n "NOTIFIED" -r app/` to see where else notified reservations are treated as active.
Hypothesis 2: `mark_notified` on the fake repository doesn't set `status` to `NOTIFIED`, or sets something else.
The failure message only tells us the status isn't `PENDING`. It doesn't confirm it's `NOTIFIED`. If the fake's `mark_notified` sets a different status (or the real and fake implementations differ), the test setup could be producing a state you didn't intend.
Check: Add a temporary `print(service.reservation_repository.get(reservation.id).status)` right before `service.cancel(...)`, or run `pytest tests/modules/reservation/test_services.py::TestCancel::test_cancels_a_notified_reservation -s` with that line in place. Also read `mark_notified` in `tests/fakes.py` and compare it to the real repository's version.
Hypothesis 3: the test is stale because the business rule changed, and notified reservations are now intentionally non-cancellable.
If a recent decision was that once a user has been notified the reservation must be fulfilled or expire, the code is right and the test is outdated. The `PENDING`-only tuple would then be deliberate rather than a leftover.
Check: `git log -n 5 --format='%h %s' -- app/modules/reservation/services.py tests/modules/reservation/test_services.py`, and look for a commit message or linked issue/spec that mentions cancelling after notification. Whichever side changed more recently is probably the one that's out of date.
One detail worth noting: the summary shows `1 failed, 1 passed, 9 deselected`, so you're running with a filter (`-k` or a node ID). That's fine here, but it's worth running the whole `TestCancel` class afterwards, since a sibling test for cancelling a pending reservation would tell you whether the guard is simply too narrow.
```
