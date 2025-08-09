# 🧠 Development Guidelines for Claude – Django Application

## 📌 General Workflow

- All tasks are tracked in GitHub Issues.
- User Stories are labeled Story
- Architectural Decisions are labeled Area/Architecture
- Each issue is implemented in a **dedicated feature branch**.
- Development follows **test-driven development (TDD)** where possible.
- All code must be **well-tested**, **linted**, and pass CI checks.
- All user interface elements must be internationalized. German is the default language setting.
- Every completed task must be submitted as a **pull request (PR)**.

---

## 🌿 Branching Strategy

- Create a new branch for every GitHub issue.
- **Branch naming convention:**
    - Enhancements: `feature/<issue-id>-<short-description>`
    - Bugfixes: `bugfix/<issue-id>-<short-description>`
- Example:
    - `feature/45-user-login`
    - `bugfix/102-fix-auth-redirect`

---

## ✅ Test-Driven Development

- Write tests **before** or alongside feature implementation.
- All code must be covered by unit or integration tests.
- Target **≥ 90% test coverage**; never reduce existing coverage.
- Use Django’s test framework or Pytest with Django integration.

---

## 🧹 Code Style & Quality

- Format code using **Black**.
- Sort imports using **isort**.
- Lint using **flake8** (and optionally `mypy`, `pylint`).
- Run formatters/linters before every commit or push.

---

## Warp Workflows (Django Guidelines)

- Open workflows in Warp:
  - Place the workflow file under `.warp/workflows` in the repo, then restart Warp or open the Workflows panel and search for "Django Guidelines".
  - Use the Command Palette (Cmd-P) to find and run workflow commands by name.
- Setting defaults:
  - In the workflow UI, set default inputs for your local clone (e.g., `settings_module`, `venv_dir`, `coverage_threshold`).
- Expected usage:
  - Before pushing or opening a PR, run: Lint (check-only), Tests with coverage (≥ 90%), `makemigrations --check`, i18n check, optional `collectstatic`, docs/changelog update, and a security scan.
  - Create branches using the provided branch commands in the workflow.
  - Use the PR helper to generate a standardized PR with "Closes #<id>".

## 🔃 Pull Request Guidelines

### 🧩 PR Naming & Description

- PR title should include the issue number:
    - `[45] Add user login`
- Link the issue in the PR description:
    - `Closes #45`

### 🔍 PR Checklist

Before marking a PR ready for review, confirm:

- [ ] Pre-push checks run via [Warp Workflows (Django Guidelines)](#warp-workflows-django-guidelines) — CI parity: CI gates mirror these commands
- [ ] **Issue linked** (`Closes #<issue-id>`)
- [ ] **Tests added/updated**
- [ ] **All tests pass**
- [ ] **Code formatted (Black, isort)**
- [ ] **No linting issues (flake8, etc.)**
- [ ] **Documentation updated (if needed)**
- [ ] **Changelog updated**
- [ ] **Self-reviewed (no TODOs, debug code, secrets, etc.)**

---

## 🚦 CI/CD Requirements

- All PRs must pass CI checks before merge:
    - ✅ Tests
    - ✅ Linters
    - ✅ Code coverage
- CI will block merges if:
    - Tests fail
    - Linting fails
    - Coverage drops below threshold
- CI parity: CI gates mirror the commands provided by the Warp workflows section

---

## 📘 Django  Project Best Practices

- Use Django’s built-in tools (ORM, admin, auth, etc.) when applicable.
- Create and include **migrations** for model changes.
- Never commit secrets or config directly.
- Follow the **DRY** principle and PEP8 style.
- Update:
    - `README.md` if usage or setup changes
    - Docstrings for new functions/classes
    - `CHANGELOG.md`

---

## 🐘 Local Postgres with Docker Compose

Use the provided docker-compose file to spin up Postgres 16 locally:

- File: `docker-compose.postgres.yml`
- Service: `db` (image: `postgres:16`)
- Env: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- Port: `5432`
- Volume: `pgdata`

Quickstart:

1) Copy the sample env and adjust if needed:
   cp .env.sample .env

2) Start Postgres:
   docker compose -f docker-compose.postgres.yml up -d

3) Verify connectivity (optional):
   docker compose -f docker-compose.postgres.yml exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT 1;"

To stop/remove:
- Stop: docker compose -f docker-compose.postgres.yml down
- Remove volume data as well: docker compose -f docker-compose.postgres.yml down -v

Notes:
- The container exposes 5432 on localhost. Update `.env` if you change ports.
- The named volume `timelog-pgdata` persists data between runs.

---

## 🗄️ Configure Django to use DATABASE_URL (psycopg)

Set DATABASE_URL in your environment (see `.env.sample`). Example:

- DATABASE_URL=postgresql://timelog:timelog@localhost:5432/timelog

Recommended settings (Django ≥ 4, psycopg 3):

- Install dependencies:
  - pip install "psycopg[binary]" dj-database-url

- In your Django settings (e.g., `project/settings.py`):

  import os
  import dj_database_url

  DATABASES = {
      "default": dj_database_url.parse(
          os.environ.get("DATABASE_URL", "postgresql://timelog:timelog@localhost:5432/timelog"),
          conn_max_age=600,
          ssl_require=False,
      )
  }

- For production, set `DATABASE_URL` and optionally `ssl_require=True` in the parse call if your provider requires SSL.
- If you prefer not to use `dj-database-url`, you can parse manually with `urllib.parse` and set `ENGINE = "django.db.backends.postgresql"`.

---

## 📄 Example Changelog Entry

```text
- Add user login page using Django built-in auth (#45)
- Fix redirect error after login (#102)
