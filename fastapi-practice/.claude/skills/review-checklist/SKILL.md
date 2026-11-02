---
name: review-checklist
description: Review a diff in a fixed order (correctness, tests, readability, security basics, scope), label each finding confirmed or unverified, and set aside findings that go against decisions agreed in the feature's spec. Reviews the range or PR the user gives, otherwise the current branch against dev. Use when asked to "review my branch", "review against dev", "review PR #N", "review this commit range", or run a review checklist before opening a PR. Read-only; never edits code.
---

# Review checklist

Review one diff. Read-only: do NOT edit, format, commit, or fix anything, even if a fix is obvious.

## 1. Pick the range

- The user gives a range (`base..head`, `base...head`, two SHAs): use it exactly as given.
- The user gives a PR number, merged or not:
  ```bash
  gh pr view <N> --json baseRefName,baseRefOid,headRefOid
  git fetch origin pull/<N>/head
  ```
  The range is `<baseRefOid>...<headRefOid>`.
- Neither: run `git fetch origin dev` and use `origin/dev...HEAD` (or `dev...HEAD` if `origin/dev` doesn't exist).

Print the range first: `Range: <range>`.

Stop and say why if the base is `main` (`main`, `origin/main`, or a PR whose `baseRefName` is `main`): `main` is empty here, so the diff would be the whole repo. Stop too if the diff is empty.

```bash
git diff <range> --stat
git diff <range>
```

Read the surrounding code of changed files when the hunk alone is not enough to judge. Read the project's CLAUDE.md if there is one; its rules count as review criteria.

## 2. Read the agreed decisions

If the diff touches `intent/<feature>/`, read the Decisions section of `intent/<feature>/spec.md` (currently `### 10.1 Decisions made during build`). Otherwise skip this step.

## 3. Review in this exact order

1. **correctness**: logic bugs, wrong conditions, off-by-one, unhandled None/empty cases, wrong error type or status code, broken contracts between layers, missing migration for a model change.
2. **tests**: changed behavior without a test, tests that don't assert the real behavior, missing error/edge cases (401/403/404/409), tests that would pass even if the code were wrong.
3. **readability**: unclear names, dead code, duplicated logic, code that doesn't match the surrounding style or the project's layering.
4. **security basics**: missing auth/role checks, secrets or credentials in code, unvalidated input, SQL built from strings, sensitive data in logs or responses.
5. **scope**: changes unrelated to the branch's purpose, stray debug code, unrelated formatting churn, files that shouldn't be committed.

Finish each category before moving to the next. Only report issues you can point to in the diff; no speculation.

## 4. Verify and sort findings

Label every finding:

- `confirmed`: you reread the code it depends on, or ran a read-only command (`git show`, `git grep`, `git log`, `uv run pytest <path>`), and it shows the problem.
- `unverified`: you could not confirm it. Say what would.

Never write a file to verify (no new tests, no temporary prints).

If step 2 ran, check each finding against the decisions. A finding that asks for the opposite of an agreed decision goes under "Against agreed decision", not under its category.

## 5. Output format

```
Range: <range>
<category> | <file>:<line> | <confirmed|unverified> | <problem>
```

Example:

```
correctness | app/modules/book/services.py:42 | confirmed | Returns 404 instead of raising ConflictError when copies run out
tests | tests/modules/book/test_router.py:88 | unverified | No test for borrowing an unavailable book; check tests/modules/book/ for one under another name
```

If a category has no findings, write `<category> | none`.

If step 2 ran, add this section. It does not count as findings:

```
Against agreed decision
<file>:<line> | <decision ID> | <what the finding wanted> vs <what the decision says>
```

If nothing goes against a decision, write `Against agreed decision | none`.

End with exactly one line:

```
Chưa kiểm tra: <what was not checked, e.g. did not run tests, did not run the app, did not check migrations against a real DB>
```
