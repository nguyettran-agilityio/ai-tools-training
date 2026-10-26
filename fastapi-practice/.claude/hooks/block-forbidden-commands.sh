#!/usr/bin/env bash
# PreToolUse hook (Bash): block commands the team forbids Claude from running.
#   - alembic upgrade (any form: alembic, uv run alembic, python -m alembic)
#   - git push to dev or main (explicit refspec, HEAD while on dev/main,
#     bare `git push` while on dev/main, --all, --mirror)
# Blocks by exiting 2 with the reason on stderr; Claude sees the reason.
set -u

if ! command -v jq >/dev/null 2>&1; then
  echo "block-forbidden-commands hook: jq not found, skipping" >&2
  exit 0
fi

command=$(jq -r '.tool_input.command // empty')
[ -n "$command" ] || exit 0

PROTECTED_BRANCHES="dev main"

block() {
  echo "Blocked by team hook: $1" >&2
  echo "Ask the user to run this themselves if it is really needed." >&2
  exit 2
}

is_protected() {
  local branch=$1
  for protected in $PROTECTED_BRANCHES; do
    [ "$branch" = "$protected" ] && return 0
  done
  return 1
}

current_branch() {
  git -C "${CLAUDE_PROJECT_DIR:-.}" rev-parse --abbrev-ref HEAD 2>/dev/null
}

# Destination branch of a push refspec: "+src:refs/heads/dst" -> "dst".
refspec_dest() {
  local spec=${1#+}
  spec=${spec##*:}
  spec=${spec#refs/heads/}
  [ "$spec" = "HEAD" ] && spec=$(current_branch)
  echo "$spec"
}

check_alembic() {
  local seen_alembic=0
  for tok in "$@"; do
    case "$tok" in
      alembic | */alembic) seen_alembic=1 ;;
      upgrade) [ "$seen_alembic" = 1 ] && block "\`alembic upgrade\` is forbidden. The user applies migrations." ;;
    esac
  done
}

check_git_push() {
  local i=0 seen_git=0 in_push=0 positional=()
  local toks=("$@")
  while [ "$i" -lt "${#toks[@]}" ]; do
    tok=${toks[$i]}
    if [ "$in_push" = 1 ]; then
      case "$tok" in
        --all | --mirror) block "\`git push $tok\` would push dev/main." ;;
        -o | --push-option | --repo | --receive-pack | --exec) i=$((i + 1)) ;;
        -*) ;;
        *) positional+=("$tok") ;;
      esac
    elif [ "$seen_git" = 1 ]; then
      case "$tok" in
        push) in_push=1 ;;
        -C | -c | --git-dir | --work-tree) i=$((i + 1)) ;;
      esac
    else
      case "$tok" in
        git | */git) seen_git=1 ;;
      esac
    fi
    i=$((i + 1))
  done

  [ "$in_push" = 1 ] || return 0

  # positional[0] is the remote; the rest are refspecs.
  if [ "${#positional[@]}" -le 1 ]; then
    branch=$(current_branch)
    is_protected "$branch" && block "\`git push\` from branch '$branch' pushes straight to $branch."
    return 0
  fi
  for spec in "${positional[@]:1}"; do
    dest=$(refspec_dest "$spec")
    is_protected "$dest" && block "pushing straight to '$dest' is forbidden. Open a PR into dev instead."
  done
}

# Split into simple commands on ; & | newline ( ) and backticks, then check each.
while IFS= read -r segment; do
  read -ra raw <<<"$segment"
  toks=()
  for t in "${raw[@]+"${raw[@]}"}"; do
    toks+=("${t//[\"\']/}")
  done
  [ "${#toks[@]}" -gt 0 ] || continue
  check_alembic "${toks[@]}"
  check_git_push "${toks[@]}"
done < <(printf '%s\n' "$command" | tr ';&|()`' '\n\n\n\n\n\n')

exit 0
