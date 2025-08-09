#!/usr/bin/env bash
set -euo pipefail

# Bootstrap utility script
# Usage: scripts/bootstrap.sh <command> [options]
#
# Environment variables (override defaults as needed):
#   python_bin  - Python interpreter to use (default: python3)
#   venv_dir    - Virtualenv directory (default: .venv)
#   manage_py   - Path to Django manage.py (default: manage.py)
#
# Commands:
#   venv-create                 Create venv if missing
#   venv-activate               Activate venv (only works when this script is sourced). If executed, prints instructions
#   pip-upgrade                 Upgrade pip; optionally install pip-tools
#   deps-install-prod           Install production dependencies from requirements.txt
#   deps-install-dev            Install development dependencies from requirements-dev.txt
#   deps-freeze                 Freeze deps to requirements.lock.txt; if pip-tools and requirements.in exist, run pip-compile --upgrade
#   django-init                 Initialize Django project/app if manage.py is missing (guarded)
#   django-config-locale        Helper to add locale settings to Django settings.py (opt-in)
#   help                        Show help

python_bin=${python_bin:-python3}
venv_dir=${venv_dir:-.venv}
manage_py=${manage_py:-manage.py}

SCRIPT_NAME=$(basename "$0")
THIS_FILE_PATH=${BASH_SOURCE[0]:-"$0"}

color() { local c=$1; shift; printf "\033[%sm%s\033[0m\n" "$c" "$*"; }
info() { color 36 "$*"; }
success() { color 32 "$*"; }
warn() { color 33 "$*"; }
err() { color 31 "$*" 1>&2; }

die() { err "$*"; exit 1; }

is_command() { command -v "$1" >/dev/null 2>&1; }

ensure_venv_python() {
  if [[ -x "$venv_dir/bin/python" ]]; then
    echo "$venv_dir/bin/python"
  else
    echo "$python_bin"
  fi
}

cmd_venv_create() {
  if [[ -d "$venv_dir" ]]; then
    success "Virtualenv already exists at $venv_dir. Nothing to do."
    exit 0
  fi
  info "Creating virtual environment at $venv_dir using $python_bin ..."
  "$python_bin" -m venv "$venv_dir"
  success "Created venv at $venv_dir"
  info "To activate: source $venv_dir/bin/activate"
}

cmd_venv_activate() {
  # If sourced, we can activate the environment in the current shell
  if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
    # Script is being sourced
    if [[ -f "$venv_dir/bin/activate" ]]; then
      # shellcheck disable=SC1090
      source "$venv_dir/bin/activate"
      success "Activated venv: $venv_dir"
    else
      die "Activate script not found at $venv_dir/bin/activate. Create the venv first (venv-create)."
    fi
  else
    warn "This command must be sourced to affect your current shell. Run:"
    echo ""
    echo "  source $THIS_FILE_PATH venv-activate"
    echo ""
  fi
}

cmd_pip_upgrade() {
  local py
  py=$(ensure_venv_python)
  info "Upgrading pip using: $py -m pip install --upgrade pip"
  "$py" -m pip install --upgrade pip
  success "pip upgraded"
  read -r -p "Install pip-tools (pip-compile, pip-sync)? [y/N] " yn
  case "$yn" in
    [Yy]*)
      info "Installing pip-tools ..."
      "$py" -m pip install pip-tools
      success "pip-tools installed"
      ;;
    *)
      info "Skipping pip-tools installation"
      ;;
  esac
}

cmd_deps_install_prod() {
  local pip
  pip=$(ensure_venv_python)
  pip="$pip -m pip"
  if [[ -f "requirements.txt" ]]; then
    info "Installing production dependencies from requirements.txt ..."
    eval "$pip install -r requirements.txt"
    success "Production dependencies installed"
  else
    die "requirements.txt not found. Create one or generate via pip-compile (if using pip-tools)."
  fi
}

cmd_deps_install_dev() {
  local pip
  pip=$(ensure_venv_python)
  pip="$pip -m pip"
  if [[ -f "requirements-dev.txt" ]]; then
    info "Installing development dependencies from requirements-dev.txt ..."
    eval "$pip install -r requirements-dev.txt"
    success "Development dependencies installed"
  else
    die "requirements-dev.txt not found. Add it or install dev deps manually."
  fi
}

cmd_deps_freeze() {
  local py pip_bin compile_bin
  py=$(ensure_venv_python)
  pip_bin="$py -m pip"

  info "Freezing current environment to requirements.lock.txt ..."
  # Use a subshell to capture the freeze output
  "$py" -m pip freeze > requirements.lock.txt
  success "Wrote requirements.lock.txt"

  if [[ -f "requirements.in" ]]; then
    if "$py" -m pip show pip-tools >/dev/null 2>&1; then
      info "pip-tools detected and requirements.in found; running pip-compile --upgrade ..."
      if is_command "$venv_dir/bin/pip-compile"; then
        "$venv_dir/bin/pip-compile" --upgrade
      else
        # Fallback to module invocation
        "$py" -m piptools compile --upgrade
      fi
      success "requirements.txt updated via pip-compile"
    else
      warn "requirements.in found but pip-tools is not installed. Run 'pip-upgrade' and choose to install pip-tools, or install it manually."
    fi
  else
    info "requirements.in not found; skipping pip-compile."
  fi
}

cmd_django_init() {
  if [[ -f "$manage_py" ]]; then
    success "Django manage.py found at $manage_py. Skipping initialization."
    return 0
  fi

  local project_name app_name py
  read -r -p "Enter Django project name: " project_name
  read -r -p "Enter Django app name: " app_name
  if [[ -z "$project_name" || -z "$app_name" ]]; then
    die "Project and app names are required."
  fi

  py=$(ensure_venv_python)

  info "Creating Django project '$project_name' in current directory ..."
  if is_command "$venv_dir/bin/django-admin"; then
    "$venv_dir/bin/django-admin" startproject "$project_name" .
  else
    if "$py" -m django --version >/dev/null 2>&1; then
      "$py" -m django startproject "$project_name" .
    else
      die "django-admin not found. Install Django first (e.g., pip install Django)."
    fi
  fi

  info "Creating Django app '$app_name' ..."
  "$py" manage.py startapp "$app_name"
  success "Django project/app created."

  cat <<'EOS'
Next steps for locale configuration (not applied automatically):
- Add a directory named 'locale' at your project root if it doesn't exist.
- In your Django settings.py, set:
    LANGUAGE_CODE = 'de'
  And ensure LOCALE_PATHS includes the project 'locale' directory, e.g.:
    from pathlib import Path
    BASE_DIR = Path(__file__).resolve().parent.parent
    LOCALE_PATHS = [ BASE_DIR / 'locale' ]

You can run the helper to attempt these changes automatically:
  scripts/bootstrap.sh django-config-locale
EOS
}

cmd_django_config_locale() {
  # Try to locate settings.py in the common locations
  local settings_file
  settings_file=$(find . -maxdepth 3 -type f -name settings.py | head -n 1 || true)
  if [[ -z "$settings_file" ]]; then
    die "Could not find settings.py. Run django-init first or specify manage_py env var correctly."
  fi

  info "Attempting to update $settings_file to set LANGUAGE_CODE='de' and ensure LOCALE_PATHS includes 'locale' ..."

  # Ensure locale directory exists
  mkdir -p ./locale

  # Add LANGUAGE_CODE or update existing one to 'de'
  if grep -E '^\s*LANGUAGE_CODE\s*=' "$settings_file" >/dev/null 2>&1; then
    sed -i.bak -E "s|^\s*LANGUAGE_CODE\s*=.*$|LANGUAGE_CODE = 'de'|" "$settings_file"
  else
    printf "\nLANGUAGE_CODE = 'de'\n" >> "$settings_file"
  fi

  # Ensure BASE_DIR is present (common in modern Django projects). If not, attempt to define it.
  if ! grep -E '^\s*BASE_DIR\s*=' "$settings_file" >/dev/null 2>&1; then
    printf "\nfrom pathlib import Path\nBASE_DIR = Path(__file__).resolve().parent.parent\n" >> "$settings_file"
  fi

  # Ensure LOCALE_PATHS includes BASE_DIR/'locale'
  if grep -E '^\s*LOCALE_PATHS\s*=' "$settings_file" >/dev/null 2>&1; then
    # Update existing list to include BASE_DIR / 'locale' if missing
    if ! grep -E "BASE_DIR\s*/\s*'locale'" "$settings_file" >/dev/null 2>&1; then
      # Append to list (simple heuristic)
      sed -i.bak -E "s|^(\s*LOCALE_PATHS\s*=\s*\[)(.*)(\])|\1 \2, BASE_DIR / 'locale' \3|" "$settings_file" || true
    fi
  else
    printf "\nLOCALE_PATHS = [ BASE_DIR / 'locale' ]\n" >> "$settings_file"
  fi

  success "Locale settings updated in $settings_file (backup saved as .bak where changes applied)."
}

show_help() {
  cat <<EOF
$SCRIPT_NAME - project bootstrapper

Environment variables:
  python_bin   Python interpreter to use (default: python3)
  venv_dir     Virtualenv directory (default: .venv)
  manage_py    Path to Django manage.py (default: manage.py)

Commands:
  venv-create            Create venv if missing
  venv-activate          Activate venv (source this script to take effect)
  pip-upgrade            Upgrade pip; optionally install pip-tools
  deps-install-prod      pip install -r requirements.txt (actionable error if missing)
  deps-install-dev       pip install -r requirements-dev.txt
  deps-freeze            pip freeze > requirements.lock.txt; if pip-tools + requirements.in, run pip-compile --upgrade
  django-init            Initialize Django project/app if manage.py missing (guarded)
  django-config-locale   Helper to modify settings.py with locale defaults
  help                   Show this help

Examples:
  python_bin=python3.12 venv_dir=.venv scripts/bootstrap.sh venv-create
  source scripts/bootstrap.sh venv-activate
  scripts/bootstrap.sh pip-upgrade
  scripts/bootstrap.sh deps-install-prod
  scripts/bootstrap.sh deps-freeze
  scripts/bootstrap.sh django-init
EOF
}

main() {
  local cmd=${1:-help}
  shift || true
  case "$cmd" in
    venv-create) cmd_venv_create "$@" ;;
    venv-activate) cmd_venv_activate "$@" ;;
    pip-upgrade) cmd_pip_upgrade "$@" ;;
    deps-install-prod) cmd_deps_install_prod "$@" ;;
    deps-install-dev) cmd_deps_install_dev "$@" ;;
    deps-freeze) cmd_deps_freeze "$@" ;;
    django-init) cmd_django_init "$@" ;;
    django-config-locale) cmd_django_config_locale "$@" ;;
    help|-h|--help) show_help ;;
    *) die "Unknown command: $cmd. Run '$SCRIPT_NAME help' for usage." ;;
  esac
}

main "$@"

