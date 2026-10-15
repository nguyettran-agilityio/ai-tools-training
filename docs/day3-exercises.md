# AI Tools Training – Day 3: Fix, review, merge

## Real example 1: Plan the fix

**Prompt v1:**

> Fix issue #7.

**Claude's answer:** It changed the code straight away, because I was not in Plan mode. It said it could not read issue #7 (`gh` is not installed), so it worked from the last commit message. It ran the tests (36 passed) and did not commit.

**Problem:** I never got to look at the plan before the code changed. I also ran this prompt first, so the next prompt found the fix already in my working tree. That made the comparison unfair.

**Prompt v2 (Plan mode):**

> Task: Plan a fix for GitHub issue #7. Do not edit any files yet.
>
> Context: In fastapi-practice/, ReservationService.cancel() in app/modules/reservation/services.py rejects NOTIFIED reservations with ConflictError (409). The failing test is tests/modules/reservation/test_services.py::TestCancel::test_cancels_a_notified_reservation.
>
> Constraints: Change only what the bug needs. Do not touch other files or refactor. Keep the existing tests unchanged.
>
> Output: A plan with (1) the root cause in one sentence, (2) the exact lines to change, (3) the files you will NOT touch, (4) how you will verify.
>
> Verify: The plan must include running the failing test, then the whole tests/modules/reservation/ folder.

**Better because:** I got a clear plan I could check before approving it: one-sentence cause, exact lines, a "will not touch" list, and test steps. I then confirmed it myself: `git diff` showed one added line, and my own pytest run gave 36 passed.

## Real example 2: GitHub Issue

**Prompt v1:**

> Write a GitHub issue for the cancel bug.

**Claude's answer:** Claude Code read the repo and `docs/day2-exercises.md` and wrote a long, detailed issue. It added sections I did not ask for (Suggested fix, Impact, Environment) and offered to run `gh issue create`.

**Problem:** It guessed which bug I meant instead of asking. It added things I had not asked for, and some numbers did not match each other, so I could not trust every detail.

**Prompt v2:**

> Draft a GitHub Issue from my Day 2 bug report below. Use ONLY the facts in the report; if something is missing (e.g. exact HTTP response), list it under "Missing info" instead of guessing.
>
> Format: Title (under 70 chars) / Summary (1-2 sentences) / Steps to reproduce (numbered) / Expected / Actual / Likely cause (mark as "suspected", file + function only) / Failing test (full pytest path).
>
> Context: FastAPI app in fastapi-practice/, cancel() in app/modules/reservation/services.py, failing test tests/modules/reservation/test_services.py::TestCancel::test_cancels_a_notified_reservation. Keep it short enough to read in 30 seconds.
>
> Bug report: (the full pytest failure output, from the `cancel()` code down to the ConflictError line)

**Better because:** The result followed my format and invented nothing. Its "Missing info" list asked a good question: did I see the bug through the API, or only in the test? My first try pasted the wrong text as the bug report, and Claude could only list missing info. A good prompt cannot make up for missing data.

## Real example 3: PR description

**Prompt v1:**

> Write a PR description for my changes.

**Claude's answer:** A long description (over 200 words) in its own format. It said I "added" `test_cancels_a_notified_reservation` and mentioned unrelated reformatting.

**Problem:** I did not name a base branch, so Claude compared against `main`. That test was already in the seed commit, so those claims were wrong.

**Prompt v2:**

> <context>
> I fixed the bug in issue #7: cancelling a NOTIFIED reservation raises ConflictError. I am on branch fix/cancel-notified-reservation. The PR is not opened yet and will target practice/seed-bug.
> </context>
>
> <task>
> Draft a PR description for my changes on the current branch compared with practice/seed-bug. Read the diff yourself with git diff practice/seed-bug...HEAD.
> </task>
>
> <constraints>
> Use ONLY facts from the diff, the commit message and issue #7. Do not invent test results.
> Keep it under 150 words.
> Do not run git push, git commit or any gh command. Do not open the PR.
> </constraints>
>
> <tests_I_ran>
> uv run pytest tests/modules/reservation/ -q -> 36 passed
> </tests_I_ran>
>
> <format>
> ## What (1-2 sentences)
> ## Why (link Closes #7, one sentence on user impact)
> ## How tested (use the commands in <tests_I_ran>; leave "[screenshot of pytest output]" as a placeholder)
> ## Notes for reviewer (files changed, what I did NOT change)
> </format>

**Better because:** The description was about 130 words with all four sections, and it did not take credit for the test from the seed commit. My first draft of this prompt had three mistakes: I called the issue a "PR #7", I wrote `seed_bug` instead of `seed-bug`, and I told Claude to run no git commands while also telling it to read the diff.

## Real example 4: Review my own PR

**Prompt v1:**

> Review my PR.

**Claude's answer:** It reviewed `dev` against `main` (141 files, about 13.6k lines), which is not what I meant.

**Problem:** I gave no target, so Claude picked one itself.

**Prompt v2:**

> Read-only task. First run `git diff 91d9aa1..origin/practice/seed-bug --stat` and show me the file list. Then review the diff `git diff 91d9aa1..origin/practice/seed-bug`. Use ONLY the diff, not your assumptions.
>
> Check 5 items: correctness, tests, readability, security basics, scope.
> For each item answer: OK / Concern, plus one sentence with the file and line.
> If you have no concern for an item, say "OK" and stop. Do not invent issues to look thorough.
> End with: the single most important concern, or "none".
> Do not edit files and do not run git push or gh.

**Claude's answer:** The file list was correct (1 file, 1 line). Readability, security and scope were OK. But it raised two concerns that were wrong: "no test coverage" (the test already existed from the seed commit) and "unclear intent" (it could not see the rest of `cancel()`).

**Problem:** My first attempt reviewed the wrong diff, because my local `practice/seed-bug` was not updated after the merge. Also, the "ONLY the diff" rule stopped Claude from reading code and tests outside the diff.

**Prompt v3 (to try next time):**

> Read-only task. First run `git diff 91d9aa1..origin/practice/seed-bug --stat` and show me the file list. Then review the diff. Use the diff as the main source. You may also read the full cancel() method and the tests in tests/modules/reservation/. If you cannot verify something, label it "unverified" instead of "Concern".
>
> Check 5 items: correctness, tests, readability, security basics, scope. For each item answer: OK / Concern / Unverified, plus one sentence with the file and line. Do not invent issues. Do not edit files.

**Better because:** It separates "I found a problem" from "I don't have enough data to know". My own review notes were right where Claude was wrong, because I had run the tests myself.

## Lesson learned

- A good prompt names the target (base branch, diff, issue) and includes real evidence like test results. Claude cannot guess these.
- "Use ONLY the facts" stops Claude from inventing things, but it can also hide context Claude needs. Let it read more, and ask it to label what it could not verify.
- When comparing a raw and an improved prompt, start each one from a clean state. Before trusting a review, check that Claude is looking at the right diff.
- Claude is a second reader, not the decider. I have the real context, so I judge each comment myself.
