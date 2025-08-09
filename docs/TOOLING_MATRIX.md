# Project Tooling and Version Matrix (Step 2)

This document records the agreed versions, tooling, and rationale to guide future setup (dependencies, CI jobs, pre-commit hooks, etc.). Use the header template below at the top of authored files to keep decisions visible.

---

Header comment template (paste at top of authored files):

"""
Project tooling/versions (Step 2 snapshot):
- Python: >=3.12,<3.14 (prefer 3.12.x; allow 3.13 if available in CI)
- Django: >=5.1,<5.2 (stable 5.1.x)
- Databases: SQLite for tests/local quick start; Postgres for production via psycopg v3
- Tests: pytest + pytest-django + coverage
- Lint/format: black, isort, flake8
- Types (optional/toggle-able): mypy + django-stubs
- Security: pip-audit (default) and safety (also supported)
"""

---

Decisions and compatible version bounds

- Python runtime:
  - Constraint: >=3.12,<3.14
  - Preference: 3.12.x as default; include 3.13 in CI matrix if available
  - Rationale: Django 5.1 supports modern Python; 3.12 is stable LTS-ish for many envs, 3.13 is acceptable where CI provides it.

- Django framework:
  - Constraint: >=5.1,<5.2 (target latest 5.1.x)
  - Rationale: Keeps within stable series while allowing patch updates.

- Databases:
  - Development/tests: SQLite (built-in, zero-config)
  - Production: PostgreSQL
    - Driver: psycopg (v3) with constraint: psycopg>=3,<4
  - Rationale: Simple local dev with SQLite; robust production with Postgres.

- Testing stack:
  - pytest: >=8,<9
  - pytest-django: >=4.8,<5
  - coverage (or coverage[toml] if using pyproject): >=7,<8
  - Rationale: Current major lines with room for patch/minor updates.

- Lint/format:
  - black: >=24,<25
  - isort: >=5.13,<6
  - flake8: >=7,<8 (with common plugins to be decided later if needed)
  - Rationale: Track current yearly Black and stable majors for others.

- Type checking (optional, toggle-able):
  - mypy: >=1.10,<2
  - django-stubs: >=5,<6
  - Enablement toggle ideas:
    - Env var: TYPECHECK=1 in CI job to run mypy
    - Optional extra: pip install .[types] locally
    - Make pre-commit hook optional

- Security tooling:
  - Default: pip-audit: >=2,<3
  - Also exposed: safety: >=3,<4
  - Rationale: pip-audit integrates with Python advisories; safety supported for orgs that prefer it.

- Auxiliary (recommended):
  - pre-commit: >=3,<4 to orchestrate formatting/lint hooks (optional but encouraged)

---

Suggested dependency groupings (for later steps)

- Runtime (minimal):
  - django>=5.1,<5.2
  - psycopg>=3,<4 (only in production or as an extra: [postgres])

- Dev/test:
  - pytest>=8,<9
  - pytest-django>=4.8,<5
  - coverage>=7,<8
  - black>=24,<25
  - isort>=5.13,<6
  - flake8>=7,<8
  - pip-audit>=2,<3
  - safety>=3,<4 (optional)
  - pre-commit>=3,<4 (optional)

- Types (optional extra [types]):
  - mypy>=1.10,<2
  - django-stubs>=5,<6

---

CI matrix (guidance for later implementation)

- OS: ubuntu-latest (primary)
- Python: [3.12, 3.13]
- Strategy:
  - Always run tests on SQLite for speed
  - Optionally add a Postgres job (services: postgres) for integration coverage
  - Separate jobs/stages:
    - lint-format (black --check, isort --check-only, flake8)
    - type-check (conditional on TYPECHECK=1)
    - test (pytest -q with coverage)
    - security (pip-audit; optionally safety)

---

Configuration hints (non-binding examples)

- pyproject.toml fragments:

  [project]
  requires-python = ">=3.12,<3.14"
  dependencies = [
    "django>=5.1,<5.2",
  ]

  [project.optional-dependencies]
  postgres = ["psycopg>=3,<4"]
  dev = [
    "pytest>=8,<9",
    "pytest-django>=4.8,<5",
    "coverage>=7,<8",
    "black>=24,<25",
    "isort>=5.13,<6",
    "flake8>=7,<8",
    "pip-audit>=2,<3",
    "safety>=3,<4",
    "pre-commit>=3,<4",
  ]
  types = [
    "mypy>=1.10,<2",
    "django-stubs>=5,<6",
  ]

- pytest.ini (example):

  [pytest]
  DJANGO_SETTINGS_MODULE = project.settings
  python_files = tests.py test_*.py *_tests.py
  addopts = -q

- mypy.ini (example; enabled when TYPECHECK=1):

  [mypy]
  python_version = 3.12
  plugins = django_stubs
  disallow_untyped_defs = True
  ignore_missing_imports = True

- pre-commit (example hooks):
  - repo: https://github.com/psf/black
    rev: 24.4.2
    hooks:
      - id: black
  - repo: https://github.com/pycqa/isort
    rev: 5.13.2
    hooks:
      - id: isort
  - repo: https://github.com/pycqa/flake8
    rev: 7.0.0
    hooks:
      - id: flake8

---

Maintenance notes

- Use compatible bounds (>=, < next-major) to allow patch/minor updates while preventing breaking changes.
- Prefer 3.12 locally; include 3.13 in CI to detect forward-compatibility issues.
- Keep the header template in new files to surface these decisions for future contributors.

