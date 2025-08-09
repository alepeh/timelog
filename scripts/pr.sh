#!/usr/bin/env bash
set -euo pipefail

# PR helper commands
#
# Usage:
#   pr_open_cli <issue_id> <pr_title...>
#   pr_open_url_template [<issue_id>] [<pr_title...>]
#
# Behavior:
# - Title format: "[#{issue_id}] {pr_title}"
# - Body includes: "Closes #{issue_id}" and a checklist copied from CLAUDE.md
# - If GitHub CLI (gh) is not installed, pr_open_cli will fall back to printing URLs via pr_open_url_template
# - pr_open_url_template prints:
#     - https://github.com/<owner>/<repo>/compare
#     - A prefilled "New pull request" URL when possible using git remote info

here() { cat <<'USAGE'
PR helper commands:

Create PR via GitHub CLI:
  pr_open_cli <issue_id> <pr_title...>

Fallback: print compare and prefilled PR URLs:
  pr_open_url_template [<issue_id>] [<pr_title...>]
USAGE
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

repo_from_git() {
  # Echo "owner repo" parsed from the current repo's origin remote
  local url
  if ! url=$(git remote get-url origin 2>/dev/null); then
    return 1
  fi
  # Normalize to https-style: https://github.com/owner/repo(.git)
  case "$url" in
    git@github.com:*)
      url="https://github.com/${url#git@github.com:}"
      ;;
  esac
  url=${url%.git}
  # Extract owner and repo
  local rest=${url#https://github.com/}
  local owner=${rest%%/*}
  local repo=${rest#*/}
  if [ -z "$owner" ] || [ -z "$repo" ]; then
    return 1
  fi
  printf "%s %s" "$owner" "$repo"
}

current_branch() {
  git rev-parse --abbrev-ref HEAD 2>/dev/null || true
}

upstream_base_branch() {
  # Try to infer base from upstream tracking ref, else default to main
  local upstream
  upstream=$(git rev-parse --abbrev-ref --symbolic-full-name @{upstream} 2>/dev/null || true)
  if [ -n "$upstream" ]; then
    # upstream like origin/main -> take part after '/'
    echo "${upstream#*/}"
  else
    # fallback
    echo "main"
  fi
}

build_title() {
  local issue_id=$1; shift
  local pr_title=${*:-}
  printf "[%s] %s" "$issue_id" "$pr_title"
}

extract_checklist_from_claude() {
  # Print checklist lines from CLAUDE.md; fallback if not available
  local file="CLAUDE.md"
  if [ -f "$file" ]; then
    # Extract section after header "### 🔍 PR Checklist" and take list items starting with - [ ]
    awk 'found==1 && $0 ~ /^- \[ \]/ {print} /### [^
]*PR Checklist/ {found=1} /^(## |# )/ && found==1 {exit}' "$file" | sed 's/\r$//' || true
  fi
}

build_body() {
  local issue_id=$1
  local checklist
  checklist=$(extract_checklist_from_claude)
  if [ -z "$checklist" ]; then
    # Default checklist if CLAUDE.md not found or no checklist present
    read -r -d '' checklist <<'DEF' || true
- [ ] Issue linked (Closes #<issue-id>)
- [ ] Tests added/updated
- [ ] All tests pass
- [ ] Code formatted (Black, isort)
- [ ] No linting issues (flake8, etc.)
- [ ] Documentation updated (if needed)
- [ ] Changelog updated
- [ ] Self-reviewed (no TODOs, debug code, secrets, etc.)
DEF
  fi
  printf "Closes #%s\n\n%s\n" "$issue_id" "$checklist"
}

urlencode() {
  # URL-encode stdin -> stdout
  # shellcheck disable=SC2018,SC2019
  local length hex c
  while IFS= read -r -n1 c; do
    case $c in
      [a-zA-Z0-9.~_-]) printf "%s" "$c" ;;
      ' ') printf '%%20' ;;
      *) printf '%%%02X' "'${c}" ;;
    esac
  done
}

prefilled_pr_url() {
  # Print a prefilled PR URL if we can detect owner/repo
  local issue_id=${1:-}
  shift || true
  local pr_title="$*"
  local owner repo
  if ! read -r owner repo < <(repo_from_git); then
    return 1
  fi
  local base head
  base=$(upstream_base_branch)
  head=$(current_branch)
  # Build title/body
  local title body
  if [ -n "$issue_id" ]; then
    title=$(build_title "$issue_id" "$pr_title")
    body=$(build_body "$issue_id")
  else
    title="$pr_title"
    body=""
  fi
  # URL encode
  local title_enc body_enc
  title_enc=$(printf "%s" "$title" | urlencode)
  body_enc=$(printf "%s" "$body" | urlencode)
  printf "https://github.com/%s/%s/compare/%s...%s?quick_pull=1&title=%s&body=%s\n" \
    "$owner" "$repo" "$base" "$head" "$title_enc" "$body_enc"
}

pr_open_cli() {
  if [ $# -lt 2 ]; then
    echo "Usage: pr_open_cli <issue_id> <pr_title...>" >&2
    return 2
  fi
  local issue_id=$1; shift
  local pr_title="$*"
  local title body
  title=$(build_title "$issue_id" "$pr_title")
  body=$(build_body "$issue_id")

  if command_exists gh; then
    # Use GH CLI directly
    gh pr create --title "$title" --body "$body" || {
      echo "gh pr create failed; falling back to URL template:" >&2
      pr_open_url_template "$issue_id" "$pr_title"
    }
  else
    echo "GitHub CLI (gh) not found; falling back to URL template:" >&2
    pr_open_url_template "$issue_id" "$pr_title"
  fi
}

pr_open_url_template() {
  # Print compare URL and prefilled PR URL if possible
  local owner repo
  if read -r owner repo < <(repo_from_git); then
    echo "https://github.com/$owner/$repo/compare"
  else
    echo "https://github.com/<owner>/<repo>/compare"
  fi
  if ! prefilled_pr_url "$@"; then
    echo "(Prefilled PR URL unavailable; ensure this is a Git repo with an 'origin' remote)" >&2
  fi
}

# If executed directly, dispatch based on first arg
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  cmd=${1:-}
  shift || true
  case "$cmd" in
    pr_open_cli) pr_open_cli "$@" ;;
    pr_open_url_template) pr_open_url_template "$@" ;;
    -h|--help|help|"") here ;;
    *) echo "Unknown command: $cmd" >&2; here; exit 1 ;;
  esac
fi
