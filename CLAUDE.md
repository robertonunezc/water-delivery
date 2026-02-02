# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Django 5.2 monolith for a water delivery business (Spanish/Mexico locale). Apps: `clients`, `core`, `orders`, `billing`, `routes`, `product`, `payment`, `report`, `notification`.

## Commands

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# Database
make migrate                          # makemigrations + migrate
python manage.py migrate              # migrate only

# Development
make runserver                        # Start dev server

# Testing
make test                             # Run all tests
python manage.py test core -q         # Single app tests

# Code quality
make format                           # black + isort
make lint                             # flake8 + pylint
```

## Architecture

### Settings
- `water_delivery/settings.py` - Base settings, loads `.env` via python-dotenv
- PostgreSQL configured via `POSTGRES_*` env vars; Redis for caching

### Core Patterns

**Soft-delete with TimeStampedModel** (`core/models.py`):
- `TimeStampedModel` provides `created_at`, `updated_at`, `deleted_at`
- `objects` (SoftDeleteManager) excludes deleted; use `all_objects` for everything
- Many app models inherit this pattern

**Service layer** (`*/services.py`):
- Domain logic spanning multiple models goes in services, not views
- All service functions must be explicitly typed and unit-tested
- Example: `orders/services.py`, `clients/services.py`
- Here the logic is for bussines logic wich coordinate process
  
**Django Models
- The model can contain businnes logic related to that entity
- Never implement logic in the models where you need authentication or anything that does
not involve models.
- Use fat models pattern
- Create managers and querysets for features like, Entity.objects.list() (to get all elements)
- First try to see if managers or querysets is a good option before creating a service.
- Avoid these in the models, (call external services, schedule background jobs,reach into other aggregates,do permission logic, manage transactions)
- Use services layer for orchestration, transactions, idempotency, calling external APIs, emitting domain events, background tasks
- Djnago Admin actions should call your services, not implement logic inline.
- If your orchestration touches multiple tables, or requires “all-or-nothing”, wrap it in:transaction.atomic()
select_for_update() where needed explicit idempotency keys for external calls.
- 

Models should not start/commit transactions.
**Balance/Credit system** (`clients/models.py`):
- `Client` model has `balance`, `credit_limit`, `current_debt` fields
- Transaction history via `BalanceTransaction` and `CreditTransaction` models
- Key methods: `add_balance()`, `deduct_balance()`, `add_debt()`, `pay_debt()`, `process_order_payment()`

**Employee/User relationship** (`core/models.py`, `core/admin.py`):
- `Employee.user` is nullable - employees can exist without system access
- User creation happens in `EmployeeAdmin.save_model()`, not via signals
- `core/signals.py` is intentionally disabled

### Docker
- `docker-compose.dev.yml` for local development
- `docker-compose.prod.yml` for production

## Code Conventions

- Type hints required for all function signatures
- Use f-strings for string formatting
- Use `logging.getLogger(__name__)` for logging
- Keep functions under 20-30 lines; extract helpers
- Domain logic in models or services, never in views

## Key Warnings

- Don't assume `Model.objects` returns all records - use `all_objects` for soft-deleted rows
- Don't modify the auth User model without careful migration planning
- Don't re-enable `core/signals.py` without reviewing admin UX
