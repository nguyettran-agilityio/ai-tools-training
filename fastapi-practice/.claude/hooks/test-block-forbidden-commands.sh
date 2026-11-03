#!/usr/bin/env bash
# Runs block-forbidden-commands.sh against fixed cases and prints a pass/fail
# table. Exits 1 if any case fails.
# Usage: .claude/hooks/test-block-forbidden-commands.sh [path/to/hook.sh]
set -u

here=$(cd "$(dirname "$0")" && pwd)
hook=${1:-$here/block-forbidden-commands.sh}
bash_bin=$(command -v bash)
command -v jq >/dev/null 2>&1 || {
  echo "jq is required to run these tests" >&2
  exit 1
}

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# Throwaway repos, so bare `git push` cases don't depend on the real checkout.
# They need a commit, or `rev-parse --abbrev-ref HEAD` prints "HEAD".
for b in feat/test dev; do
  repo=$work/${b%%/*}
  git init -q -b "$b" "$repo"
  git -C "$repo" -c user.name=test -c user.email=test@example.com commit -q --allow-empty -m init
done
# Empty dir as PATH: the hook can't find jq.
mkdir "$work/nojq"

pass=0
fail=0
num=0

# Args: expected (block|allow), command, [repo], [PATH], [text the stderr must contain]
run_case() {
  local expect=$1 cmd=$2 repo=${3:-$work/feat} path=${4:-$PATH} must=${5:-}
  local code actual result
  num=$((num + 1))
  jq -n --arg c "$cmd" '{tool_name: "Bash", tool_input: {command: $c}}' >"$work/in.json"
  PATH=$path CLAUDE_PROJECT_DIR=$repo "$bash_bin" "$hook" <"$work/in.json" >/dev/null 2>"$work/err"
  code=$?
  case "$code" in
    0) actual=allow ;;
    2) actual=block ;;
    *) actual="error" ;;
  esac
  result=PASS
  [ "$actual" = "$expect" ] || result=FAIL
  if [ -n "$must" ] && ! grep -qF "$must" "$work/err"; then
    result="FAIL (message lacks: $must)"
  fi
  if [ "$result" = PASS ]; then pass=$((pass + 1)); else fail=$((fail + 1)); fi
  printf '| %2d | %-72s | %-6s | %-5s (%d) | %s |\n' "$num" "$cmd" "$expect" "$actual" "$code" "$result"
}

printf '| %2s | %-72s | %-6s | %-9s | %s |\n' "#" "Command" "Expect" "Actual" "Result"
printf '|----|%s|--------|-----------|--------|\n' "$(printf -- '-%.0s' $(seq 74))"

run_case block 'uv run alembic upgrade head' "" "" "in their own terminal"
run_case block 'cd fastapi-practice && uv run alembic upgrade head'
run_case allow 'git commit -m "Migration not applied; run alembic upgrade head yourself"'
run_case allow 'echo "alembic upgrade" > notes.txt'
run_case block 'git push origin dev'
run_case allow 'git push origin feat/x'
run_case allow 'git push'
run_case block 'bash -c "uv run alembic upgrade head"'
run_case block 'uv run python -m alembic upgrade head'
run_case allow 'git commit -m "fix; alembic upgrade later"'
run_case allow 'uv run alembic current'
run_case block 'git push' "$work/dev"
run_case block "sh -c 'cd app; alembic upgrade head'"
run_case block 'eval "uv run alembic upgrade head"'
run_case block 'echo "$(uv run alembic upgrade head)"'
run_case block 'env DATABASE_URL=sqlite:///x.db uv run alembic upgrade head'
run_case allow 'uv run alembic revision --autogenerate -m "upgrade users"'
run_case block 'uv run alembic current' "" "$work/nojq" "install jq"

echo
echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
