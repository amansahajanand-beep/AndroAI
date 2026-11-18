# Database

PostgreSQL 16, SQLAlchemy 2.x (sync, psycopg 3), Alembic. Only a **baseline migration (`0001`, no tables)** exists. Tables are added by the feature that needs them.

## Connection

`DATABASE_URL=postgresql://user:pass@host:5432/db` (the API rewrites it to the `postgresql+psycopg://` driver). Engine is lazy: `androai_api.db.get_engine()`. Sessions via the `get_db` FastAPI dependency. Connectivity: `check_database()` → `/api/v1/health/ready`.

## Migrations

Run from `apps/api`:

```bash
alembic upgrade head                           # apply
alembic revision --autogenerate -m "add projects table"
alembic downgrade -1
```

`migrations/env.py` takes the URL from app settings, never from `alembic.ini`.

### How a new module introduces tables

1. Define models subclassing `androai_api.db.Base` in your module.
2. Import that module in `androai_api/db/models.py` so autogenerate sees it.
3. `alembic revision --autogenerate -m "<message>"`, **review the generated file by hand**, commit it.
4. Never edit a migration that has been merged; add a new one.
5. Keep one linear history: if `alembic heads` shows two heads after a merge, run `alembic merge heads`.
6. Constraint names follow the naming convention in `db/base.py`.

Migration ownership: Person 4 reviews all migrations.
