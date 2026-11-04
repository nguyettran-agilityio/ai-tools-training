---
name: review-checklist
description: "Review a diff in a fixed order (correctness, tests, readability, security basics, scope), label each finding confirmed or unverified, and set aside findings that go against decisions agreed in the feature's spec. Reviews the range or PR the user gives, otherwise the current branch against dev. Use when asked to 'review my branch', 'review against dev', 'review PR #N', 'review this commit range', or run a review checklist before opening a PR. Read-only; never edits code."
---

# Review checklist

This is a checklist for reviewing consistently. It does not replace `/code-review` or ultrareview for finding logic bugs.

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

Read the surrounding code of changed files when the hunk alone is not enough to judge. If the range's head is not `HEAD` (compare `git rev-parse <head>` with `git rev-parse HEAD`), read files as they are at the head: `git show <head>:./<file>`, never from the working tree. Read the project's CLAUDE.md if there is one; its rules count as review criteria.

## 2. Read the agreed decisions

Always read specs from current dev, not from the range's head: a decision may be written down after the PR merged.

```bash
git fetch origin dev
git ls-tree --name-only origin/dev ./intent/
```

A feature in `intent/<feature>/` is in scope when the diff changes `intent/<feature>/`, or when the diff only changes code but the branch name, PR title, commit messages, or issue numbers match that feature (its folder name, or an issue number that appears in its files), or the changed files are ones its spec names.

For each feature in scope, read the Decisions section of the spec (currently `### 10.1 Decisions made during build`):

```bash
git show origin/dev:./intent/<feature>/spec.md
```

Print what you read: `Spec: intent/<feature>/spec.md @ origin/dev <short SHA>`, or `Spec: none` if no feature is in scope.

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

Never write a file to verify (no new tests, no temporary prints, no checkout of the head). Tests run against the working tree, so when the range's head is not `HEAD`, a test run only covers `HEAD`.

If step 2 read a spec, check each finding against its decisions. A finding that asks for the opposite of an agreed decision goes under "Against agreed decision", not under its category.

## 5. Output format

```
Range: <range>
Spec: <spec read, or none>
<category> | <file>:<line> | <confirmed|unverified> | <problem>
```

Example:

```
correctness | app/modules/book/services.py:42 | confirmed | Returns 404 instead of raising ConflictError when copies run out
tests | tests/modules/book/test_router.py:88 | unverified | No test for borrowing an unavailable book; check tests/modules/book/ for one under another name
```

If a category has no findings, write `<category> | none`.

If step 2 read a spec, add this section. It does not count as findings:

```
Against agreed decision
<file>:<line> | <decision ID> | <what the finding wanted> vs <what the decision says>
```

If nothing goes against a decision, write `Against agreed decision | none`.

End with exactly one line:

```
Chưa kiểm tra: <what was not checked, e.g. did not run tests, did not run the app, did not check migrations against a real DB; if tests ran on HEAD instead of the range's head, say so>
```
