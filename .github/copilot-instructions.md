Project: water-delivery — Copilot instructions for coding agents

Purpose
- Help an AI contributor become productive quickly by documenting project-specific structure, conventions, workflows, and common operations.

Quick architecture summary
- Django 5.2 monolith with multiple Django apps under the repo root: `clients`, `core`, `orders`, `billing`, `routes`, `product`, `payment`, `report`, `notification`.
- `water_delivery/` contains Django settings and WSGI/ASGI entrypoints. `settings.py` loads `.env` via `python-dotenv`; `settings_development.py` and `settings_production.py` provide environment-specific overrides.
- Data flows: most domain logic lives in app `models.py` and `services.py` (e.g., `orders/services.py`). `clients` implements balance/credit history with transaction models — see `tests/` demo scripts for examples of usage.

Important project conventions & patterns
- Time-stamped / soft-delete pattern:
  - `core.models.TimeStampedModel` provides `created_at`, `updated_at`, `deleted_at`.
  - `SoftDeleteManager` (default) filters out soft-deleted rows; `all_objects` returns all.
  - Many app models inherit `TimeStampedModel`. Prefer `objects` (default) unless you explicitly need soft-deleted rows.

- Admin and user/employee handling:
  - `core.models.Employee.user` is nullable: employees can exist without a linked `User` account (they may not access the system).
  - `core/admin.py` intentionally does NOT inline `Employee` into the `User` admin: create/manage employees from the `Employee` admin only.
  - `EmployeeAdmin.save_model()` will create a `User` with an unusable password if saving an employee without a linked user — check `core/admin.py` for the logic.
  - There is a disabled `core/signals.py` file (used to auto-create Employees on User creation previously). Signals are not imported on app ready; employee creation is explicit.

- DB & infra conventions:
  - Uses PostgreSQL (see `requirements.txt`) and Redis. DB config is environment-variable driven (`POSTGRES_*`) in `water_delivery/settings.py`.
  - Docker Compose files exist: `docker-compose.dev.yml` and `docker-compose.prod.yml` for local/dev/prod orchestration.

Dev workflows & commands (copy-paste)
- Local setup (venv + deps):
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  ```
- Migrations / DB:
  ```bash
  make migrate
  # or
  python manage.py makemigrations
  python manage.py migrate
  ```
- Run dev server:
  ```bash
  make runserver
  ```
- Run tests:
  ```bash
  make test
  # or run single app
  python manage.py test core -q
  ```
- Formatting / linting:
  ```bash
  make format
  make lint
  ```

Key files to inspect when making changes
- `core/models.py` — TimeStampedModel, SoftDeleteManager, `Employee` model.
- `core/admin.py` — admin UX and `EmployeeAdmin.save_model` logic (user creation from employee admin).
- `core/apps.py` — app config; check for signal imports.
- `clients/models.py` — balance / credit transaction implementation and domain methods used across the app.
- `orders/services.py` — example of service-layer logic interacting with domain models.
- `Makefile` — canonical shortcut commands for install/migrate/runserver/test/lint/format.

Testing notes and conventions
- There are both unit tests in each app and some top-level demo/test scripts under `tests/` which set up Django programmatically. Use `python manage.py test` for standard test discovery.
- Many models rely on the `TimeStampedModel` behavior; when writing tests that need soft-deleted records, use `Model.all_objects` where appropriate.

Integration points & external dependencies
- Postgres: configured by environment variables (`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`).
- Redis: used by the project (see `requirements.txt`) — check caches/settings if you need to run integration tests involving Redis.
- Jazzmin: customized admin theme (`jazzmin` in `INSTALLED_APPS`). Admin customizations are in per-app `admin.py` files.

When to be careful
- Avoid changing the auth user model. The project uses Django's built-in `User` model; altering this requires a full migration strategy and coordination across the codebase.
- Soft-delete: don't assume `Model.objects` returns all records. Use `all_objects` when querying historical/soft-deleted rows.
- Signals: `core/signals.py` is intentionally disabled; do not re-enable automatic employee creation without reviewing `core/admin.py` UX requirements.

Examples (code pointers)
- Create an employee and link a user from admin: see `core/admin.py:EmployeeAdmin.save_model`.
- Balance history demo: `tests/test_balance_credit_history.py` shows how to use `Client.add_balance`, `deduct_balance`, `add_debt` and `pay_debt`.

If you need more
- Ask for: (1) a migration generated for a model change, (2) a bulk admin action to create users for employees missing them, or (3) a short walkthrough to run the app via Docker Compose.

If anything here is unclear or missing, tell me which area you'd like expanded (e.g., API routes, important service functions, or test coverage hotspots).
