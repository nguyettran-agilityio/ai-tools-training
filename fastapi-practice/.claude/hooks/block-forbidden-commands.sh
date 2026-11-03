#!/usr/bin/env bash
# PreToolUse hook (Bash): block commands the team forbids Claude from running.
#   - alembic upgrade, only when alembic is the command being run: first word,
#     or after VAR=..., env, uv run, python -m. Text inside a string
#     (commit message, echo) does not count.
#   - git push to dev or main (explicit refspec, HEAD while on dev/main,
#     bare `git push` while on dev/main, --all, --mirror)
# Scripts given to bash -c / sh -c / eval, and "$(...)" or `...` inside double
# quotes, are checked too.
# Blocks by exiting 2 with the reason on stderr; Claude sees the reason.
set -u

block() {
  echo "Blocked by team hook: $1" >&2
  echo "${2:-Ask the user to run this themselves if it is really needed.}" >&2
  exit 2
}

if ! command -v jq >/dev/null 2>&1; then
  block "jq is not installed, so this hook cannot check the command." \
    "Stop and ask the user to install jq (e.g. \`brew install jq\`), then retry."
fi

command=$(jq -r '.tool_input.command // empty')
[ -n "$command" ] || exit 0

# Fast path: nothing to check, skip the char-by-char parse below.
case "$command" in
  *alembic* | *push*) ;;
  *) exit 0 ;;
esac

PROTECTED_BRANCHES="dev main"
MAX_DEPTH=5

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

# Args: the tokens after `alembic`. Only the subcommand (first non-option
# token) counts, so `alembic revision -m "upgrade users"` is allowed.
check_alembic() {
  local skip=0 tok
  for tok in "$@"; do
    if [ "$skip" = 1 ]; then
      skip=0
      continue
    fi
    case "$tok" in
      -c | --config | -n | --name | -x) skip=1 ;;
      -*) ;;
      upgrade)
        block "\`alembic upgrade\` is forbidden: Claude never applies migrations." \
          "If a migration needs applying, stop here and ask the user to run \`uv run alembic upgrade head\` in their own terminal. Continue only after they confirm it ran."
        ;;
      *) return 0 ;;
    esac
  done
}

# Args: the tokens after `git`.
check_git_push() {
  local i=0 in_push=0 tok spec dest branch
  local toks=("$@") positional=()
  while [ "$i" -lt "${#toks[@]}" ]; do
    tok=${toks[$i]}
    if [ "$in_push" = 1 ]; then
      case "$tok" in
        --all | --mirror) block "\`git push $tok\` would push dev/main." ;;
        -o | --push-option | --repo | --receive-pack | --exec) i=$((i + 1)) ;;
        -*) ;;
        *) positional+=("$tok") ;;
      esac
    else
      case "$tok" in
        push) in_push=1 ;;
        -C | -c | --git-dir | --work-tree) i=$((i + 1)) ;;
        -*) ;;
        *) return 0 ;; # subcommand is not push, e.g. `git commit -m push`
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

# Args: depth, then the tokens of one simple command (quotes already removed).
# Skips VAR=... / env / uv run / python -m wrappers to find the command that
# actually runs, then checks it.
check_simple_command() {
  local depth=$1
  shift
  local t=("$@")
  local i=0 j n=${#t[@]} found w
  while [ "$i" -lt "$n" ]; do
    case "${t[$i]}" in
      [A-Za-z_]*=*) i=$((i + 1)) ;;
      # Reserved words that start a command: `then cmd`, `do cmd`, `{ cmd`, `! cmd`.
      if | then | else | elif | while | until | do | '{' | '!') i=$((i + 1)) ;;
      env | */env)
        i=$((i + 1))
        while [ "$i" -lt "$n" ]; do
          case "${t[$i]}" in
            -u | --unset | -C | --chdir) i=$((i + 2)) ;;
            -* | [A-Za-z_]*=*) i=$((i + 1)) ;;
            *) break ;;
          esac
        done
        ;;
      exec | command | nohup | time | sudo)
        w=${t[$i]}
        i=$((i + 1))
        while [ "$i" -lt "$n" ]; do
          case "${t[$i]}" in
            -u | -g | -U | -C | -D | -p | -r | -t | -T | --user | --group | \
              --other-user | --close-from | --chdir | --prompt | --role | --type | \
              --command-timeout)
              # sudo options that take a value: `sudo -u root cmd`.
              if [ "$w" = sudo ]; then i=$((i + 2)); else i=$((i + 1)); fi
              ;;
            -*) i=$((i + 1)) ;;
            *) break ;;
          esac
        done
        ;;
      uv | */uv | uvx | */uvx)
        # uv run / uv tool run / uvx, then their options.
        case "${t[$i]} ${t[$((i + 1))]:-} ${t[$((i + 2))]:-}" in
          uvx\ * | */uvx\ *) i=$((i + 1)) ;;
          *\ run\ *) i=$((i + 2)) ;;
          *\ tool\ run) i=$((i + 3)) ;;
          *) return 0 ;;
        esac
        while [ "$i" -lt "$n" ]; do
          case "${t[$i]}" in
            --from | --with | --with-editable | --with-requirements | --python | -p | \
              --project | --directory | --package | --env-file | --extra | \
              --group | --only-group | --no-group | --index | --default-index)
              i=$((i + 2))
              ;;
            -*) i=$((i + 1)) ;;
            *) break ;;
          esac
        done
        ;;
      python | python3 | python3.* | */python | */python3 | */python3.*)
        # python [opts] -m alembic ...: continue at the module name.
        j=$((i + 1))
        found=0
        while [ "$j" -lt "$n" ]; do
          case "${t[$j]}" in
            -m)
              found=1
              j=$((j + 1))
              break
              ;;
            -*) j=$((j + 1)) ;;
            *) break ;;
          esac
        done
        [ "$found" = 1 ] || return 0
        i=$j
        ;;
      alembic | */alembic)
        check_alembic "${t[@]:$((i + 1))}"
        return 0
        ;;
      git | */git)
        check_git_push "${t[@]:$((i + 1))}"
        return 0
        ;;
      bash | sh | zsh | dash | ksh | */bash | */sh | */zsh | */dash | */ksh)
        # bash [opts] -c 'script' ...: check the script.
        j=$((i + 1))
        while [ "$j" -lt "$n" ]; do
          case "${t[$j]}" in
            -o | +o) j=$((j + 2)) ;;
            --*) j=$((j + 1)) ;;
            -*c*)
              check_command $((depth + 1)) "${t[$((j + 1))]:-}"
              return 0
              ;;
            -*) j=$((j + 1)) ;;
            *) return 0 ;; # runs a script file, nothing to check here
          esac
        done
        return 0
        ;;
      eval)
        check_command $((depth + 1)) "${t[*]:$((i + 1))}"
        return 0
        ;;
      *) return 0 ;;
    esac
  done
}

# Args: depth, command line. Splits it into simple commands on ; & | ( ) `
# and newlines outside quotes, removes quotes, and checks each one.
# "$(...)" and `...` inside double quotes also run, so they are checked as
# command lines of their own.
check_command() {
  local depth=$1 s=$2
  [ "$depth" -le "$MAX_DEPTH" ] || block "command is nested too deeply to check."
  local seg=() tok="" has_tok=0 q="" c i=0 k d n=${#s}

  while [ "$i" -lt "$n" ]; do
    c=${s:$i:1}
    if [ "$q" = "'" ]; then
      if [ "$c" = "'" ]; then q=""; else tok+=$c; fi
    elif [ "$q" = '"' ]; then
      case "$c" in
        '"') q="" ;;
        '\')
          i=$((i + 1))
          tok+=${s:$i:1}
          ;;
        '$')
          if [ "${s:$((i + 1)):1}" = "(" ]; then
            k=$((i + 2))
            d=1
            while [ "$k" -lt "$n" ] && [ "$d" -gt 0 ]; do
              case "${s:$k:1}" in
                '(') d=$((d + 1)) ;;
                ')') d=$((d - 1)) ;;
              esac
              k=$((k + 1))
            done
            check_command $((depth + 1)) "${s:$((i + 2)):$((k - i - 3))}"
            i=$((k - 1))
          else
            tok+=$c
          fi
          ;;
        '`')
          k=$((i + 1))
          while [ "$k" -lt "$n" ] && [ "${s:$k:1}" != '`' ]; do k=$((k + 1)); done
          check_command $((depth + 1)) "${s:$((i + 1)):$((k - i - 1))}"
          i=$k
          ;;
        *) tok+=$c ;;
      esac
    else
      case "$c" in
        "'" | '"')
          q=$c
          has_tok=1
          ;;
        '\')
          i=$((i + 1))
          [ "${s:$i:1}" = $'\n' ] || {
            tok+=${s:$i:1}
            has_tok=1
          }
          ;;
        ' ' | $'\t' | ';' | '&' | '|' | '(' | ')' | '`' | $'\n')
          if [ "$has_tok" = 1 ]; then
            seg+=("$tok")
            tok=""
            has_tok=0
          fi
          case "$c" in
            ' ' | $'\t') ;;
            *)
              [ "${#seg[@]}" -gt 0 ] && check_simple_command "$depth" "${seg[@]}"
              seg=()
              ;;
          esac
          ;;
        *)
          tok+=$c
          has_tok=1
          ;;
      esac
    fi
    i=$((i + 1))
  done

  [ "$has_tok" = 1 ] && seg+=("$tok")
  [ "${#seg[@]}" -gt 0 ] && check_simple_command "$depth" "${seg[@]}"
  return 0
}

check_command 0 "$command"
exit 0
