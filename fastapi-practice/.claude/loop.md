Check the open pull request for the current branch with gh.
- The PR must target dev. If it targets main, stop and tell me.
- For each new review comment: make the smallest change that addresses it, run the tests for the touched module plus ruff and mypy, commit with a message starting with a capital letter, push, and reply on the PR starting with "(Claude)".
- If the branch is behind dev or has conflicts, tell me. Do not rebase or merge on your own.
- Never merge the PR, never push to dev or main, never run alembic upgrade.
- If nothing changed, say so in one line.
