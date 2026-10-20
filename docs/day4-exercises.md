# Day 04 Exercise – Bug tickets

## Notes

- Goal: take a bug ticket through the full loop: plan, approve, implement, read the diff, test, review in a clean session, commit on a fix branch, open a PR.
- I made the fix branches separate from the practice branches that hold the bug commit.
- I opened each PR against the practice branch, so the bug commit does not reach dev or main.
- Both tickets were guided step by step. I did not work alone, so Ticket 2 does not count as the "no help" run.

## Real example

Prompt v1 and Prompt v2 are for two different tickets. Ticket 1 is BUG-1 (borrow limit) and Ticket 2 is BUG-2 (author search).

### Prompt v1 (Ticket 1)

```
<task>Fix the following bug. Do not fix the code yet, write a plan first.
BUG-1: A member can borrow more books than the allowed limit.
Steps: a member logs in, BORROW_LIMIT=5 (default), borrows 5 different books with POST /borrowings, then borrows a 6th book that still has copies available.
Expected: the 6th request returns 409 Conflict with a message that the limit was reached.
Actual: the 6th request succeeds. Only from the 7th book is it blocked.</task>
<constraints>Only fix within the scope of this bug. Do not change existing tests. State which files you read and what is still "unverified".</constraints>
<verification>After the fix, run: cd fastapi-practice && uv run pytest tests/modules/borrowing -q. Show me the output before the fix and after the fix. All tests must pass.</verification>
```

### Claude's answer (Ticket 1)

- Claude found that commit 4e75fa6 changed `>=` to `>` in the borrow-limit check in `services.py`, and it changed it back.
- Before the fix, 3 tests failed (57 passed). After the fix, 60 passed.
- `git status` showed one modified file. I also ran the tests and the full suite myself.
- PR #12 was created: base practice/bug-1, head fix/bug-1-borrow-limit, +1 -1.

### Problem (Ticket 1)

I was in Plan mode, but I never saw a plan. I only saw questions asking me to allow commands. I allowed them, and then Claude edited the file. I do not know why.

My first `/code-review` answer read like a chat reply. It said "4 issues" but described only 3. Its wording suggested it knew the session's history, so it may not have been a clean review. A review in a new session found no problems.

### Prompt v2 (Ticket 2)

I ran this prompt in Vietnamese. My study chat wrote it and I ran it as given. The version below is an English translation.

```
<task>Find the cause and write a plan to fix the following bug. DO NOT fix the code yet, only write a plan for me to review.

BUG-2: Book search doesn't find books by part of the author's name.
Steps: seed sample data, with a book by the author "J.R.R. Tolkien" (for example "The Hobbit"). Call GET /books?q=tolkien, then compare with GET /books?q=J.R.R
Expected: both return "The Hobbit". Search is case-insensitive and matches any part of the title or the author's name.
Actual: q=tolkien returns an empty list (total = 0). Only q=J.R.R finds it.</task>
<evidence>Before the fix: uv run pytest tests/modules/book -q gives 3 failed, 310 passed. The three failing tests:
- tests/modules/book/test_repositories.py::TestBookRepositorySearch::test_query_only_matches_title_or_author_case_insensitive (assert 0 == 1)
- tests/modules/book/test_routers.py::TestListBooks::test_q_matches_title_case_insensitive (result set differs from expected)
- tests/modules/book/test_routers.py::TestListBooks::test_q_matches_author (assert 0 == 1)</evidence>
<constraints>I don't know where the bug is, find it yourself. Only fix within the scope of this bug. Do not change existing tests. State which files you read and what is still "unverified". If the plan changes more than a few files, explain the reason for each file.</constraints>
<verification>After the fix, run: uv run pytest tests/modules/book -q. Show me the output before and after. All 313 tests must pass.</verification>
```

### Claude's answer (Ticket 2)

Claude gave a plan first, before any edit.

- Cause: commit 10d1e9a ("Tidy book search filters") removed the leading `%` in `Book.author.ilike(...)` in `repositories_sqlmodel.py`, so the author matched only at the start of the text.
- Fix: restore the leading `%` (one line). I checked this with `git show 10d1e9a`.
- I approved the plan, Claude edited the file, and `git diff` showed one file and one line.
- Tests: tests/modules/book 53 passed, full suite 313 passed.
- A review in a new session found no problems in the diff. It named two older issues on the same line: no escaping of `%` and `_`, and `ilike` on SQLite only ignoring case for ASCII letters. I did not verify those two.
- PR created: base practice/bug-2, head fix/bug-2-author-search, 1 file changed. I checked this with `gh pr view`.

### Problem (Ticket 2)

Claude's plan said the module has 53 tests (3 failed, 50 passed), not 3 failed and 310 passed. The numbers in my prompt did not match the command I named: 313 is the full suite, and 53 is `tests/modules/book`. The error was in my prompt, and Claude flagged the mismatch itself as "unverified".

I also first thought I had to know where the bug was before writing the prompt. That was wrong. The prompt needs the symptom, the evidence (the failing tests), the constraints and the check. Finding the cause is Claude's job in plan mode.

### Better because

The plan appeared before any edit and I could read it. I read `git diff` myself, I ran the tests myself, and the review happened in a clean session. I do not know why Plan mode behaved differently from Ticket 1.

## Lesson learned

A bug prompt needs symptom, evidence, constraints and a check. I do not need to know the cause. Check every number against the command that produced it, including numbers that Claude or my own prompt gives me.
