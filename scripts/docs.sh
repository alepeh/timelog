#!/usr/bin/env bash
set -euo pipefail

# Documentation and Changelog helper commands
# Usage: scripts/docs.sh <command> [options]
#
# Commands:
#   open-readme                     Open README.md in $EDITOR (fallback to nano/vi)
#   changelog-add-entry             Add an entry under [Unreleased] in CHANGELOG.md
#       args:
#         --issue <id>              Issue ID/number (required)
#         --title <text>            Short title/summary (required)
#         --type <Added|Changed|Fixed|Removed>  Change type (required)
#         --body <text>             Optional detailed body (use literal \n for newlines)
#   sweep-docstrings                List Python files with TODOs or missing module docstrings
#       args:
#         --open                    Open results in $EDITOR one by one
#   verify-docs-updated             Heuristic check that README/CHANGELOG updated when code changed
#       args:
#         --ci                      Exit non-zero when docs appear missing (CI parity)
#
# Notes:
# - CHANGELOG.md will be created with a Keep a Changelog skeleton if missing.
# - README.md will be created with a minimal header if missing.

SCRIPT_NAME=$(basename "$0")
EDITOR_CMD=${EDITOR:-}

color() { local c=$1; shift; printf "\033[%sm%s\033[0m\n" "$c" "$*"; }
info() { color 36 "$*"; }
success() { color 32 "$*"; }
warn() { color 33 "$*"; }
err() { color 31 "$*" 1>&2; }

die() { err "$*"; exit 1; }

ensure_readme() {
  if [[ ! -f README.md ]]; then
    info "README.md not found. Creating a minimal README.md ..."
    cat > README.md <<'MD'
# Project README

Describe your project here.

- Setup: see scripts/bootstrap.sh and Makefile
- Docs: see docs/ directory
- Changelog: see CHANGELOG.md
MD
    success "Created README.md"
  fi
}

ensure_changelog() {
  if [[ ! -f CHANGELOG.md ]]; then
    info "CHANGELOG.md not found. Creating Keep a Changelog skeleton ..."
    cat > CHANGELOG.md <<'MD'
# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to Semantic Versioning.

## [Unreleased] - YYYY-MM-DD
### Added
### Changed
### Fixed
### Removed

MD
    success "Created CHANGELOG.md"
  fi
}

cmd_open_readme() {
  ensure_readme
  local ed
  if [[ -n "$EDITOR_CMD" ]]; then
    ed="$EDITOR_CMD"
  elif command -v nano >/dev/null 2>&1; then
    ed="nano"
  else
    ed="vi"
  fi
  info "Opening README.md with $ed ..."
  "$ed" README.md
}

# Args: --issue, --title, --type, --body
cmd_changelog_add_entry() {
  ensure_changelog
  local issue="" title="" type="" body=""
  while (($#)); do
    case "$1" in
      --issue) issue=${2:-}; shift 2;;
      --title) title=${2:-}; shift 2;;
      --type) type=${2:-}; shift 2;;
      --body) body=${2:-}; shift 2;;
      *) die "Unknown option: $1";;
    esac
  done
  [[ -z "$issue" ]] && die "--issue is required"
  [[ -z "$title" ]] && die "--title is required"
  [[ -z "$type" ]] && die "--type is required (Added|Changed|Fixed|Removed)"
  case "$type" in
    Added|Changed|Fixed|Removed) ;;
    *) die "--type must be one of: Added, Changed, Fixed, Removed";;
  esac

  # Ensure the [Unreleased] section exists with standard subsections
  if ! grep -qE '^## \[Unreleased\]' CHANGELOG.md; then
    printf '\n## [Unreleased] - YYYY-MM-DD\n### Added\n### Changed\n### Fixed\n### Removed\n' >> CHANGELOG.md
  fi
  # Also ensure all four headings exist under Unreleased (order preserved)
  awk '
    BEGIN{in_unrel=0; have_added=0; have_changed=0; have_fixed=0; have_removed=0}
    /^## \[Unreleased\]/{in_unrel=1}
    in_unrel && /^### Added$/{have_added=1}
    in_unrel && /^### Changed$/{have_changed=1}
    in_unrel && /^### Fixed$/{have_fixed=1}
    in_unrel && /^### Removed$/{have_removed=1}
    {print}
    END{
      if (!(have_added && have_changed && have_fixed && have_removed)){
        print "### Added";
        print "### Changed";
        print "### Fixed";
        print "### Removed";
      }
    }
  ' CHANGELOG.md > CHANGELOG.md.tmp && mv CHANGELOG.md.tmp CHANGELOG.md

  local entry="- ${type}: ${title} (#${issue})"
  if [[ -n "$body" ]]; then
    # Replace literal \n with actual newlines, indent body lines by two spaces
    local formatted_body
    formatted_body=$(printf "%s" "$body" | sed 's/\\n/\n/g' | sed 's/^/  /')
    entry+=$'\n'"$formatted_body"
  fi

  # Insert entry right after the "### {type}" within Unreleased
  awk -v t="$type" -v new="$entry" '
    BEGIN{in_unrel=0; printed=0}
    /^## \[Unreleased\]/{in_unrel=1}
    in_unrel && $0=="### " t && !printed {print; print new; printed=1; next}
    {print}
  ' CHANGELOG.md > CHANGELOG.md.tmp && mv CHANGELOG.md.tmp CHANGELOG.md

  success "Appended changelog entry under [Unreleased] -> $type"
}

cmd_sweep_docstrings() {
  local do_open=0
  if [[ "${1:-}" == "--open" ]]; then
    do_open=1
    shift || true
  fi

  info "Scanning for TODO/FIXME and missing module docstrings ..."
  # Detect TODO/FIXME
  echo "== TODO/FIXME occurrences =="
  if command -v rg >/dev/null 2>&1; then
    rg -n "TODO|FIXME" --glob "*.py" --hidden -g '!{.venv,venv,node_modules,.git}/*' || true
  else
    grep -R -n -E "TODO|FIXME" --include "*.py" -- . \
      --exclude-dir .venv --exclude-dir venv --exclude-dir node_modules --exclude-dir .git || true
  fi

  echo
  echo "== Missing module docstrings (AST-based) =="
  if command -v python >/dev/null 2>&1; then
    python - <<'PY'
import os, ast
exclude_dirs = {'.venv','venv','node_modules','.git'}
for root, dirs, files in os.walk('.'):
    if any(part in exclude_dirs for part in root.split(os.sep)):
        continue
    for f in files:
        if not f.endswith('.py'): continue
        p = os.path.join(root, f)
        try:
            with open(p, 'r', encoding='utf-8') as fh:
                src = fh.read()
            mod = ast.parse(src)
            if ast.get_docstring(mod) is None:
                print(p)
        except Exception:
            pass
PY
  else
    warn "python not found; skipping docstring AST check"
  fi

  if [[ $do_open -eq 1 ]]; then
    local ed
    if [[ -n "$EDITOR_CMD" ]]; then
      ed="$EDITOR_CMD"
    elif command -v nano >/dev/null 2>&1; then
      ed="nano"
    else
      ed="vi"
    fi
    echo
    echo "Opening files with missing module docstrings, one by one. Close the editor to continue."
    while read -r file; do
      [[ -z "$file" ]] && continue
      "$ed" "$file"
    done < <(python - <<'PY'
import os, ast
exclude_dirs = {'.venv','venv','node_modules','.git'}
for root, dirs, files in os.walk('.'):
    if any(part in exclude_dirs for part in root.split(os.sep)):
        continue
    for f in files:
        if not f.endswith('.py'): continue
        p = os.path.join(root, f)
        try:
            with open(p, 'r', encoding='utf-8') as fh:
                src = fh.read()
            mod = ast.parse(src)
            if ast.get_docstring(mod) is None:
                print(p)
        except Exception:
            pass
PY
)
  fi
}

cmd_verify_docs_updated() {
  local ci_mode=0
  if [[ "${1:-}" == "--ci" ]]; then
    ci_mode=1
    shift || true
  fi
  # Get changed files in last commit range
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    warn "Not a git repository; skipping docs verification."
    exit 0
  fi
  mapfile -t changed < <(git --no-pager diff --name-only HEAD~1..HEAD || true)
  if [[ ${#changed[@]} -eq 0 ]]; then
    info "No files changed in last commit; nothing to verify."
    exit 0
  fi
  local code_changed=0 docs_changed=0
  for f in "${changed[@]}"; do
    case "$f" in
      *.py|*.js|*.ts|*.tsx|*.jsx|*.go|*.rs|*.java|*.kt|*.c|*.cc|*.cpp|*.h|*.hpp|*.rb|*.php|*.sh|*.yaml|*.yml|*.toml|*.ini|*.cfg|Dockerfile*|Makefile)
        code_changed=1 ;;
    esac
    case "$f" in
      README.md|CHANGELOG.md)
        docs_changed=1 ;;
    esac
  done

  if [[ $code_changed -eq 1 && $docs_changed -eq 0 ]]; then
    warn "Code changed but README.md/CHANGELOG.md did not. Consider updating docs/changelog."
    echo "Changed files:"
    printf ' - %s\n' "${changed[@]}"
    if [[ $ci_mode -eq 1 ]]; then
      exit 2
    fi
  else
    success "Docs verification passed (or no code changes)."
  fi
}

show_help() {
  cat <<EOF
$SCRIPT_NAME - docs and changelog helpers

Commands:
  open-readme
  changelog-add-entry --issue <id> --title <text> --type <Added|Changed|Fixed|Removed> [--body <text>]
  sweep-docstrings [--open]
  verify-docs-updated [--ci]
EOF
}

main() {
  local cmd=${1:-help}
  shift || true
  case "$cmd" in
    open-readme) cmd_open_readme "$@" ;;
    changelog-add-entry) cmd_changelog_add_entry "$@" ;;
    sweep-docstrings) cmd_sweep_docstrings "$@" ;;
    verify-docs-updated) cmd_verify_docs_updated "$@" ;;
    help|-h|--help) show_help ;;
    *) die "Unknown command: $cmd. Run '$SCRIPT_NAME help' for usage." ;;
  esac
}

main "$@"
