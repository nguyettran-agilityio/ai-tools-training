# AI Tools Training – Day 3: Fix, review, merge

## Real example 1: Plan the fix

**Prompt v1:**

> Fix issue #7.

**Claude's answer:** It edited the code right away (not in Plan mode). It said it couldn't read issue #7 because `gh` isn't installed and worked from the last commit message. It ran the tests (36 passed) and committed nothing.

**Problem:** I had no chance to review the direction before the code changed. I also ran the raw prompt first, so the improved prompt later found the fix already in my working tree. That spoiled the comparison.

**Prompt v2 (Plan mode):**

> Task: Plan a fix for GitHub issue #7. Do not edit any files yet.
> Context: `ReservationService.cancel()` rejects NOTIFIED reservations with ConflictError (409). Failing test: `...::test_cancels_a_notified_reservation`.
> Constraints: Change only what the bug needs. Do not touch other files or refactor.
> Output: (1) root cause in one sentence, (2) exact lines to change, (3) files you will NOT touch, (4) how you will verify.
> Verify: run the failing test, then the whole `tests/modules/reservation/` folder.

**Better because:** The plan had a one-sentence root cause, the exact lines, a "will not touch" list and verification steps, so I could check it before approving. I confirmed myself: `git diff` showed 1 added line, and my own pytest run gave 36 passed.

## Real example 2: GitHub Issue

**Prompt v1:**

> Write a GitHub issue for the cancel bug.

**Claude's answer:** Claude Code read the repo and `docs/day2-exercises.md` and wrote a detailed issue. It added sections I never asked for (Suggested fix, Impact, Environment) and offered to run `gh issue create`.

**Problem:** It guessed which bug I meant instead of asking. Some details I had not verified (the test counts contradicted each other). It went beyond my scope.

**Prompt v2:**

> Draft a GitHub Issue from my Day 2 bug report below. Use ONLY the facts in the report; if something is missing, list it under "Missing info" instead of guessing.
> Format: Title / Summary / Steps to reproduce / Expected / Actual / Likely cause (mark as "suspected") / Failing test.
> Bug report: [real pytest traceback]

**Better because:** The output followed my format exactly and did not invent anything. Its "Missing info" list asked the right question (seen through the API or only in the test?). Note: my first attempt pasted the wrong text as the bug report, and Claude could only list missing info. A good prompt cannot replace missing data.

## Real example 3: PR description

**Prompt v1:**

> Write a PR description for my changes.

**Claude's answer:** A long description (200+ words) in its own format. It claimed I "added" `test_cancels_a_notified_reservation` and mentioned unrelated reformatting.

**Problem:** I gave no base branch, so Claude compared against `main`. The test was already in the seed commit, so those claims were wrong.

**Prompt v2 (my own XML structure, then fixed):**

> `<context>` fix for issue #7, branch `fix/cancel-notified-reservation`, PR will target `practice/seed-bug`
> `<task>` draft a PR description from `git diff practice/seed-bug...HEAD`
> `<constraints>` use ONLY the diff, the commit message and issue #7; under 150 words; no push, no commit, no `gh`
> `<tests_I_ran>` `uv run pytest tests/modules/reservation/ -q` -> 36 passed
> `<format>` What / Why / How tested / Notes for reviewer

**Better because:** About 130 words, four sections, and it did not take credit for the seed test. My draft had 3 mistakes: I wrote "PR #7" for an issue, `seed_bug` instead of `seed-bug`, and told it to run no git commands while also telling it to read the diff.

## Real example 4: Review my own PR

**Prompt v1:**

> Review my PR.

**Claude's answer:** It reviewed `dev` against `main` (141 files, about 13.6k lines), which is not what I meant.

**Problem:** With no review target, Claude chose its own.

**Prompt v2:**

> Read-only task. First run `git diff 91d9aa1..origin/practice/seed-bug --stat` and show me the file list. Then review the diff. Use ONLY the diff.
> Check correctness, tests, readability, security basics, scope. For each: OK / Concern + one sentence. Do not invent issues.

**Claude's answer:** The `--stat` was correct (1 file, 1 line). Correctness, tests and scope were fine, but it raised two wrong concerns: "no test coverage" (the test already exists from the seed commit) and "unclear intent" (it could not see the rest of `cancel()`).

**Problem:** My first attempt reviewed the wrong diff, because my local `practice/seed-bug` was not pulled after the merge. The "ONLY the diff" rule also made Claude blind to context outside the diff.

**Prompt v3 (to try next time):**

> Use the diff as the main source. You may also read the full method and the related tests. Mark anything you could not verify as "unverified", not "Concern".

**Better because:** It separates "I found a problem" from "I lack the data to know". My own notes were right where Claude was wrong, because I had run the tests myself.

## Lesson learned

- A good prompt names the target (base branch, diff, issue) and gives real evidence (test results). Claude does not know these by itself.
- "Use ONLY the facts" stops invention but can remove needed context. Allow extra reading and ask for "unverified" labels.
- Run each prompt on a clean state when comparing raw and improved, and check that Claude is looking at the right diff before trusting its review.
- Claude is the second reader, not the decider. I have the real context, so I judge each comment.
