# Test and Django utility commands
# Usage examples:
#   make test                          # run all tests (pytest if available, else Django test)
#   make test-cov COVERAGE_THRESHOLD=85 # run all tests with coverage, failing under threshold
#   make test-app APP=myapp             # run tests for a Django app/package
#   make test-node NODE=tests/test_file.py::TestClass::test_case
#   make test-last-failed               # quickly run only last failed tests (pytest only)
#   make migrate                        # apply Django migrations
#   make makemigrations                 # create migrations for all apps
#   make makemigrations-app APP=myapp   # create migrations for a specific app
#   make makemigrations-check           # check for missing migrations (CI parity)
#   make showmigrations                 # list migrations and applied status
#   make squashmigrations APP=myapp FROM=0001 TO=0010 CONFIRM=1  # squash migrations (guarded)
#   make db-engine                      # print current DB engine from Django settings
#   make db-check-postgres              # try connecting to Postgres using DATABASE_URL or PG* env vars
#   make flush CONFIRM=1                # flush test DB (guarded; requires CONFIRM=1)
#   make createsuperuser                # create superuser (uses DJANGO_SUPERUSER_* if set)
#   make show-test-settings             # print DJANGO_SETTINGS_MODULE and DB engine

# Configurable variables
MANAGE_PY ?= manage.py
SETTINGS_MODULE ?= $(DJANGO_SETTINGS_MODULE)
COVERAGE_THRESHOLD ?= 80
# i18n defaults
DEFAULT_LANGUAGE ?= de
VENV_DIR ?= .venv

# Detect pytest once at parse time
PYTEST := $(shell command -v pytest 2>/dev/null)

# Internal helpers
ifeq ($(strip $(SETTINGS_MODULE)),)
SETTINGS_FLAG :=
PY_SETTINGS_EXPORT :=
else
SETTINGS_FLAG := --settings=$(SETTINGS_MODULE)
PY_SETTINGS_EXPORT := DJANGO_SETTINGS_MODULE=$(SETTINGS_MODULE)
endif
# .PHONY: test test-cov test-app test-node test-last-failed migrate flush createsuperuser show-test-settings \
	makemigrations makemigrations-app makemigrations-check showmigrations squashmigrations db-engine db-check-postgres \
	lint lint-check lint-black lint-black-check lint-isort lint-isort-check lint-flake8 \
	security-bandit security-pip-audit security-safety security-all \
	i18n-makemessages i18n-compilemessages i18n-verify-untranslated i18n-ensure-settings i18n-ensure-settings-patch i18n-check-messages-updated \
	docs-open-readme changelog-add-entry docs-sweep-docstrings docs-verify-docs-updated
	docs-open-readme changelog-add-entry docs-sweep-docstrings docs-verify-docs-updated
test:
ifeq ($(PYTEST),)
	@echo "pytest not found; falling back to: python $(MANAGE_PY) test $(SETTINGS_FLAG)"
	@python $(MANAGE_PY) test $(SETTINGS_FLAG)
else
	@$(PY_SETTINGS_EXPORT) pytest -q
endif

# Tests: Run all with coverage (fail under ${COVERAGE_THRESHOLD})
# Note: Coverage-based run requires pytest and pytest-cov.
test-cov:
ifeq ($(PYTEST),)
	@echo "pytest not found; cannot run coverage. Falling back to Django test without coverage." && \
	python $(MANAGE_PY) test $(SETTINGS_FLAG)
else
	@$(PY_SETTINGS_EXPORT) pytest --cov=. --cov-report=term-missing --cov-fail-under=$(COVERAGE_THRESHOLD) --maxfail=1 -q
endif

# Tests: Run for app (APP=app_label)
# Example: make test-app APP=myapp
test-app:
	@if [ -z "$(APP)" ]; then echo "Error: APP is required (e.g., make test-app APP=myapp)"; exit 2; fi
ifeq ($(PYTEST),)
	@echo "pytest not found; running Django tests for app: $(APP)" && \
	python $(MANAGE_PY) test $(APP) $(SETTINGS_FLAG)
else
	@$(PY_SETTINGS_EXPORT) pytest $(APP) -q
endif

# Tests: Run for file/node (NODE=path_or_nodeid)
# Example: make test-node NODE=tests/test_models.py::TestModel::test_str
test-node:
	@if [ -z "$(NODE)" ]; then echo "Error: NODE is required (e.g., make test-node NODE=tests/test_models.py::TestModel::test_str)"; exit 2; fi
ifeq ($(PYTEST),)
	@echo "pytest not found; running Django tests (may not support node ids): $(NODE)" && \
	python $(MANAGE_PY) test $(NODE) $(SETTINGS_FLAG)
else
	@$(PY_SETTINGS_EXPORT) pytest $(NODE) -q
endif

# Tests: Last failed quick (pytest only)
# Runs only last failures with exit-on-first-fail for quick feedback
test-last-failed:
ifeq ($(PYTEST),)
	@echo "pytest not found; last-failed mode is unavailable. Running full Django test suite instead." && \
	python $(MANAGE_PY) test $(SETTINGS_FLAG)
else
	@$(PY_SETTINGS_EXPORT) pytest --lf -x -q
endif

# Tests: Django test DB migrate (SQLite or configured DB)
migrate:
	@python $(MANAGE_PY) migrate $(SETTINGS_FLAG)

# -----------------------------------------------------------------------------
# Django Migrations Management
# -----------------------------------------------------------------------------

# Create migrations for all apps
makemigrations:
	@python $(MANAGE_PY) makemigrations $(SETTINGS_FLAG)

# Create migrations for a specific app (APP=app_label)
makemigrations-app:
	@if [ -z "$(APP)" ]; then echo "Error: APP is required (e.g., make makemigrations-app APP=myapp)"; exit 2; fi
	@python $(MANAGE_PY) makemigrations $(APP) $(SETTINGS_FLAG)

# Check for missing migrations (CI parity)
makemigrations-check:
	@python $(MANAGE_PY) makemigrations --check --dry-run $(SETTINGS_FLAG)

# Show migrations and their applied status
showmigrations:
	@python $(MANAGE_PY) showmigrations $(SETTINGS_FLAG)

# Squash migrations (guarded)
# Usage: make squashmigrations APP=myapp FROM=0001_initial TO=0010_auto CONFIRM=1
squashmigrations:
	@if [ "$(CONFIRM)" != "1" ]; then \
		echo "Guarded: set CONFIRM=1 to proceed (this rewrites migration history)"; \
		exit 2; \
	fi
	@if [ -z "$(APP)" ] || [ -z "$(FROM)" ] || [ -z "$(TO)" ]; then \
		echo "Error: APP, FROM and TO are required (e.g., make squashmigrations APP=myapp FROM=0001_initial TO=0010_auto CONFIRM=1)"; \
		exit 2; \
	fi
	@echo "Squashing migrations for app=$(APP) from=$(FROM) to=$(TO) ..."
	@python $(MANAGE_PY) squashmigrations $(APP) $(FROM) $(TO) $(SETTINGS_FLAG)
)

# Tests: Django test DB flush (guarded)
# Require CONFIRM=1 to proceed, to avoid accidental data loss in dev DB.
flush:
	@if [ "$(CONFIRM)" != "1" ]; then \
		echo "Guarded: set CONFIRM=1 to proceed (e.g., make flush CONFIRM=1)"; \
		exit 2; \
	fi
	@python $(MANAGE_PY) flush --noinput $(SETTINGS_FLAG)

# Tests: Create superuser (optional)
# If DJANGO_SUPERUSER_* env vars are set, use --noinput for non-interactive creation.
createsuperuser:
	@if [ -n "$$DJANGO_SUPERUSER_USERNAME" ] || [ -n "$$DJANGO_SUPERUSER_EMAIL" ] || [ -n "$$DJANGO_SUPERUSER_PASSWORD" ]; then \
		echo "Creating superuser non-interactively using DJANGO_SUPERUSER_* env vars"; \
		python $(MANAGE_PY) createsuperuser --noinput $(SETTINGS_FLAG) || true; \
	else \
		echo "Launching interactive createsuperuser"; \
		python $(MANAGE_PY) createsuperuser $(SETTINGS_FLAG); \
	fi

# Tests: Show test Django settings in effect
# Prints DJANGO_SETTINGS_MODULE and database ENGINE.
show-test-settings:
	@echo "DJANGO_SETTINGS_MODULE=$${DJANGO_SETTINGS_MODULE:-$(SETTINGS_MODULE)}"
	@$(PY_SETTINGS_EXPORT) python - <<'PY'
from __future__ import annotations
import os
try:
    from django.conf import settings
    # Accessing settings may require setup in standalone scripts
    if not settings.configured:
        import django
        django.setup()
    db = settings.DATABASES.get('default', {})
    engine = db.get('ENGINE', '(not set)')
    name = db.get('NAME', '(not set)')
    print(f"DATABASE.ENGINE={engine}")
    print(f"DATABASE.NAME={name}")
except Exception as e:
    print(f"Error importing Django settings: {e}")
PY

# DB: Show current DB engine (minimal; honors DJANGO_SETTINGS_MODULE/SETTINGS_MODULE)
# Equivalent to: python -c "import importlib; s=importlib.import_module('${settings_module}'); print(s.DATABASES['default']['ENGINE'])"
db-engine:
	@python - <<'PY'
import importlib, os, sys
mod = os.environ.get('DJANGO_SETTINGS_MODULE') or os.environ.get('SETTINGS_MODULE') or "$(SETTINGS_MODULE)"
if not mod:
    print("DJANGO_SETTINGS_MODULE is not set and SETTINGS_MODULE default is empty.")
    sys.exit(2)
s = importlib.import_module(mod)
print(s.DATABASES.get('default', {}).get('ENGINE'))
PY

# DB: Postgres connection check (prod-like; optional)
# Uses DATABASE_URL or PG* env vars: PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE
# Example: make db-check-postgres DATABASE_URL=postgres://user:***@host:5432/dbname
# Note: Do not echo secrets; this only prints non-sensitive connection info.
db-check-postgres:
	@python - <<'PY'
import os, sys
host = os.environ.get('PGHOST', 'localhost')
port = int(os.environ.get('PGPORT', '5432'))
user = os.environ.get('PGUSER')
db   = os.environ.get('PGDATABASE')
url  = os.environ.get('DATABASE_URL')
use_psycopg3 = True
conn = None
try:
    try:
        import psycopg
    except Exception:
        use_psycopg3 = False
        import psycopg2 as psycopg
    if url:
        if use_psycopg3:
            conn = psycopg.connect(url, connect_timeout=5)
        else:
            conn = psycopg.connect(url, connect_timeout=5)
    else:
        params = {
            'host': host,
            'port': port,
            'user': user,
            'dbname': db,
            'connect_timeout': 5,
        }
        # Only include password if provided (do not print it)
        pwd = os.environ.get('PGPASSWORD')
        if pwd:
            params['password'] = pwd
        if use_psycopg3:
            conn = psycopg.connect(**params)
        else:
            conn = psycopg.connect(**params)
    with conn.cursor() as cur:
        cur.execute('SELECT 1')
        cur.fetchone()
    print('Postgres connection OK:', end=' ')
    safe_user = user or ('URL' if url else '(unknown)')
    safe_db = db or ('URL' if url else '(unknown)')
    print(f'user={safe_user} dbname={safe_db} host={host} port={port}')
except Exception as e:
    print('Postgres connection FAILED:', str(e))
    sys.exit(1)
finally:
    try:
        if conn is not None:
            conn.close()
    except Exception:
        pass
PY

# -----------------------------------------------------------------------------
# Lint and Format commands
# -----------------------------------------------------------------------------

# Lint: black fix
lint-black:
	@black .

# Lint: black check (CI parity)
lint-black-check:
	@black --check --diff .

# Lint: isort fix
lint-isort:
	@isort .

# Lint: isort check (CI parity)
lint-isort-check:
	@isort --check-only --diff .

# Lint: flake8
lint-flake8:
	@flake8 .

# Lint: All (fix mode) — run black, isort, flake8 in sequence; fail if any fails.
lint: lint-black lint-isort lint-flake8
	@echo "Lint (fix) completed"

# Lint: All (check-only, CI parity) — run black --check, isort --check-only, flake8; fail if any fails.
lint-check: lint-black-check lint-isort-check lint-flake8
	@echo "Lint (check) completed"

# -----------------------------------------------------------------------------
# Security / Safety audit commands
# -----------------------------------------------------------------------------

# Security: bandit (static analysis for Python security issues)
# Usage: make security-bandit
security-bandit:
	@if ! command -v bandit >/dev/null 2>&1; then \
		echo "Error: bandit is not installed. Install with: pip install bandit"; \
		exit 2; \
	fi
	@echo "Running bandit (recursive, excluding tests,migrations, level=low, include all)")
	@bandit -r . -x tests,migrations -ll -iii

# Security: pip-audit (dependency vulnerability scan)
# Usage: make security-pip-audit
security-pip-audit:
	@if ! command -v pip-audit >/dev/null 2>&1; then \
		echo "Error: pip-audit is not installed. Install with: pip install pip-audit"; \
		exit 2; \
	fi
	@set -e; \
	ARGS=""; \
	[ -f requirements.txt ] && ARGS="$$ARGS -r requirements.txt"; \
	[ -f requirements-dev.txt ] && ARGS="$$ARGS -r requirements-dev.txt"; \
	set +e; \
	pip-audit $$ARGS; STATUS=$$?; \
	if [ "$$STATUS" -ne 0 ]; then \
		echo; \
		echo "pip-audit found vulnerabilities."; \
		echo "Remediation guidance:"; \
		echo "  - Prefer: pip-audit --fix (will attempt to bump versions safely)"; \
		echo "  - Or: update pinned versions in your requirements files and re-run the audit"; \
		echo "  - If unavoidable, pin with a known-vulnerable version only with justification and a follow-up task"; \
		echo "  - Re-run: make security-pip-audit"; \
	fi; \
	exit $$STATUS

# Security: safety (alternative dependency vulnerability scanner)
# Usage: make security-safety
security-safety:
	@if ! command -v safety >/dev/null 2>&1; then \
		echo "Error: safety is not installed. Install with: pip install safety"; \
		exit 2; \
	fi
	@set -e; \
	ARGS=""; \
	[ -f requirements.txt ] && ARGS="$$ARGS -r requirements.txt"; \
	[ -f requirements-dev.txt ] && ARGS="$$ARGS -r requirements-dev.txt"; \
	set +e; \
	safety check $$ARGS; STATUS=$$?; \
	if [ "$$STATUS" -ne 0 ]; then \
		echo; \
		echo "safety found vulnerabilities."; \
		echo "Remediation guidance:"; \
		echo "  - Update pinned versions in your requirements files to non-vulnerable releases"; \
		echo "  - Consider replacing/patching packages with no fixed versions"; \
		echo "  - If temporarily ignoring, annotate with justification and expiry in CI config"; \
		echo "  - Re-run: make security-safety"; \
	fi; \
	exit $$STATUS

# Security: all (run bandit + dependency audit) with remediation guidance
# Usage: make security-all [PIP_TOOL=pip-audit|safety]
# Defaults to pip-audit; set PIP_TOOL=safety to use safety instead.
security-all:
	@set -e; \
	BANDIT_OK=0; DEP_OK=0; \
	if command -v bandit >/dev/null 2>&1; then \
		set +e; bandit -r . -x tests,migrations -ll -iii; BSTAT=$$?; set -e; \
		if [ "$$BSTAT" -ne 0 ]; then BANDIT_OK=1; fi; \
	else \
		echo "Warning: bandit not installed; skipping. Install with: pip install bandit"; \
		BANDIT_OK=1; \
	fi; \
	PIP_TOOL_CMD="pip-audit"; \
	if [ "$(PIP_TOOL)" = "safety" ]; then PIP_TOOL_CMD="safety"; fi; \
	if ! command -v $$PIP_TOOL_CMD >/dev/null 2>&1; then \
		echo "Warning: $$PIP_TOOL_CMD not installed; skipping dependency audit"; \
		DEP_OK=1; \
	else \
		ARGS=""; [ -f requirements.txt ] && ARGS="$$ARGS -r requirements.txt"; [ -f requirements-dev.txt ] && ARGS="$$ARGS -r requirements-dev.txt"; \
		set +e; \
		if [ "$$PIP_TOOL_CMD" = "pip-audit" ]; then \
			pip-audit $$ARGS; DSTAT=$$?; \
		else \
			safety check $$ARGS; DSTAT=$$?; \
		fi; \
		set -e; \
		if [ "$$DSTAT" -ne 0 ]; then DEP_OK=1; fi; \
	fi; \
	if [ "$$BANDIT_OK" -ne 0 ] || [ "$$DEP_OK" -ne 0 ]; then \
		echo; echo "One or more security checks reported issues."; \
		echo "Remediation guidance:"; \
		echo "  Code (bandit):"; \
		echo "    - Review each finding and refactor risky code (e.g., unsafe eval/exec, subprocess shell=True, weak hashes)"; \
		echo "    - Use least-privilege patterns; sanitize inputs; avoid hardcoded secrets; prefer safe libraries"; \
		echo "    - Mark false-positives with '# nosec' only with justification in code review"; \
		echo "  Dependencies:"; \
		echo "    - Prefer: pip-audit --fix (if using pip-audit) to bump to a safe version"; \
		echo "    - Otherwise: update requirements pins and test; consider package replacements if no fix exists"; \
		echo "    - Track ignored findings with expiry and rationale in CI"; \
		exit 1; \
	else \
		echo "Security checks passed with no reported issues"; \
	fi

# -----------------------------------------------------------------------------
# i18n commands (German default)
# -----------------------------------------------------------------------------

# i18n: makemessages (de)
# Usage: make i18n-makemessages [DEFAULT_LANGUAGE=de] [VENV_DIR=.venv]
i18n-makemessages:
	@echo "Running makemessages for language=$(DEFAULT_LANGUAGE) (excluding $(VENV_DIR), node_modules, static/build)"
	@django-admin makemessages -l $(DEFAULT_LANGUAGE) -i $(VENV_DIR) -i node_modules -i static/build -e py,html,txt

# i18n: compilemessages
# Usage: make i18n-compilemessages [DEFAULT_LANGUAGE=de]
i18n-compilemessages:
	@echo "Compiling messages for language=$(DEFAULT_LANGUAGE)"
	@django-admin compilemessages -l $(DEFAULT_LANGUAGE)

# i18n: verify untranslated strings
# If msgattrib is available, use it; otherwise, fallback to a grep heuristic excluding header
# Usage: make i18n-verify-untranslated [DEFAULT_LANGUAGE=de]
i18n-verify-untranslated:
	@set -e; \
	PO_FILE="locale/$(DEFAULT_LANGUAGE)/LC_MESSAGES/django.po"; \
	if [ ! -f "$$PO_FILE" ]; then \
		echo "PO file not found: $$PO_FILE"; \
		exit 2; \
	fi; \
	if command -v msgattrib >/dev/null 2>&1; then \
		echo "Checking untranslated entries using msgattrib..."; \
		UNTRANS=$$(msgattrib --untranslated "$$PO_FILE"); \
		echo "--- First 200 lines of untranslated entries (if any) ---"; \
		echo "$$UNTRANS" | sed -n '1,200p'; \
		COUNT=$$(echo "$$UNTRANS" | grep '^msgid "' | grep -v '^msgid ""' | wc -l | tr -d ' '); \
		if [ "$$COUNT" -gt 0 ]; then \
			echo "Found $$COUNT untranslated message entries"; \
			exit 1; \
		else \
			echo "No untranslated entries found"; \
		fi; \
	else \
		echo "msgattrib not found; using grep-based heuristic..."; \
		# Heuristic: count msgid lines that are not the header (msgid "") and whose next msgstr is empty
		COUNT=$$(awk 'BEGIN{RS=""} /\nmsgid \"/ { if ($$0 !~ /\nmsgid \"\"\n/) { if ($$0 ~ /\nmsgstr \"\"\n/) c++ } } END{print c+0}' "$$PO_FILE"); \
		if [ "$$COUNT" -gt 0 ]; then \
			echo "Found $$COUNT untranslated message entries (heuristic)"; \
			# Print first 200 lines of file to aid debugging
			sed -n '1,200p' "$$PO_FILE"; \
			exit 1; \
		else \
			echo "No untranslated entries found (heuristic)"; \
		fi; \
	fi

# i18n: ensure LOCALE_PATHS and LANGUAGE_CODE=de in settings (non-destructive guidance)
# Prints guidance and a suggested diff/patch. Use the -patch target to apply automatically (guarded).
# Usage: make i18n-ensure-settings [SETTINGS_FILE=path/to/settings.py] [DEFAULT_LANGUAGE=de]
i18n-ensure-settings:
	@echo "--- i18n settings guidance ---"; \
	SETTINGS_FILE="$(SETTINGS_FILE)"; \
	if [ -z "$$SETTINGS_FILE" ]; then \
		if [ -n "$(SETTINGS_MODULE)" ]; then \
			python - <<'PY'
import os, importlib, inspect
mod = os.environ.get('DJANGO_SETTINGS_MODULE') or os.environ.get('SETTINGS_MODULE')
try:
    m = importlib.import_module(mod)
    p = inspect.getsourcefile(m)
    print(p or '')
except Exception:
    pass
PY
		else \
			true; \
		fi; \
	fi; \
	echo; echo "Ensure your Django settings contain:"; echo; \
	echo "    LANGUAGE_CODE = '$(DEFAULT_LANGUAGE)'"; \
	echo "    LOCALE_PATHS = [BASE_DIR / 'locale']"; \
	echo; \
	echo "Suggested patch (contextual; adjust as needed):"; echo; \
	echo "--- a/settings.py"; \
	echo "+++ b/settings.py"; \
	echo "@@"; \
	echo " LANGUAGE_CODE = '$(DEFAULT_LANGUAGE)'"; \
	echo " LOCALE_PATHS = [BASE_DIR / 'locale']"; \
	echo; \
	echo "To auto-patch: make i18n-ensure-settings-patch SETTINGS_FILE=path/to/settings.py CONFIRM=1"

# i18n: guarded auto-patch variant using sed with backup files
# Usage: make i18n-ensure-settings-patch SETTINGS_FILE=path/to/settings.py CONFIRM=1
# Creates a .bak backup of the settings file before editing.
i18n-ensure-settings-patch:
	@if [ -z "$(SETTINGS_FILE)" ]; then echo "Error: SETTINGS_FILE is required (e.g., make i18n-ensure-settings-patch SETTINGS_FILE=project/settings.py CONFIRM=1)"; exit 2; fi
	@if [ "$(CONFIRM)" != "1" ]; then echo "Guarded: set CONFIRM=1 to proceed"; exit 2; fi
	@echo "Patching $(SETTINGS_FILE) (backup: $(SETTINGS_FILE).bak)"; \
	sed -i.bak -E "s/^LANGUAGE_CODE\s*=.*/LANGUAGE_CODE = '$(DEFAULT_LANGUAGE)'/" "$(SETTINGS_FILE)" || true; \
	if ! grep -q "^LANGUAGE_CODE\s*=" "$(SETTINGS_FILE)"; then \
		echo "\nLANGUAGE_CODE = '$(DEFAULT_LANGUAGE)'" >> "$(SETTINGS_FILE)"; \
	fi; \
	if grep -q "^LOCALE_PATHS\s*=" "$(SETTINGS_FILE)"; then \
		sed -i.bak -E "s/^LOCALE_PATHS\s*=.*/LOCALE_PATHS = [BASE_DIR \/ 'locale']/" "$(SETTINGS_FILE)"; \
	else \
		echo "LOCALE_PATHS = [BASE_DIR / 'locale']" >> "$(SETTINGS_FILE)"; \
	fi; \
	echo "Done. Review changes with: git --no-pager diff $(SETTINGS_FILE)"

# i18n: check messages updated (CI parity)
# Runs makemessages and then checks that locale/ has no diffs; restores changes afterward.
# Usage: make i18n-check-messages-updated [DEFAULT_LANGUAGE=de]
	i18n-check-messages-updated:
	@echo "Running makemessages (check-only) and verifying no changes under locale/ ..."; \
	django-admin makemessages -l $(DEFAULT_LANGUAGE) -i $(VENV_DIR) -i node_modules -i static/build -e py,html,txt; \
	git --no-pager diff --exit-code -- locale || (echo 'Translation files are out-of-date. Run: make i18n-makemessages' && exit 1); \
	git checkout -- locale || true

# -----------------------------------------------------------------------------
# Docs and Changelog helpers
# -----------------------------------------------------------------------------

docs-open-readme:
	@bash scripts/docs.sh open-readme

# Usage example:
#   make changelog-add-entry ISSUE=123 TITLE="Fix crash on startup" TYPE=Fixed BODY="Handled None case\nImproved logging"
changelog-add-entry:
	@if [ -z "$(ISSUE)" ] || [ -z "$(TITLE)" ] || [ -z "$(TYPE)" ]; then \
		echo "Usage: make changelog-add-entry ISSUE=<id> TITLE=<text> TYPE=<Added|Changed|Fixed|Removed> [BODY=<text>]"; \
		exit 2; \
	fi
	@bash scripts/docs.sh changelog-add-entry --issue "$(ISSUE)" --title "$(TITLE)" --type "$(TYPE)" $(if $(BODY),--body "$(BODY)")

# Optional interactive sweep to address TODOs and missing module docstrings
# Usage: make docs-sweep-docstrings [OPEN=1]
docs-sweep-docstrings:
	@if [ "$(OPEN)" = "1" ]; then \
		bash scripts/docs.sh sweep-docstrings --open; \
	else \
		bash scripts/docs.sh sweep-docstrings; \
	fi

# Heuristic verification that docs were updated when code changed
# Usage: make docs-verify-docs-updated [CI=1]
docs-verify-docs-updated:
	@if [ "$(CI)" = "1" ]; then \
		bash scripts/docs.sh verify-docs-updated --ci; \
	else \
		bash scripts/docs.sh verify-docs-updated; \
	fi
