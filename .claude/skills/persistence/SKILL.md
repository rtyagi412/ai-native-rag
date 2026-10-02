---
name: persistence
description: Rules for relational database schema and data writes in backend services. Use whenever designing a data model, creating or changing tables, entities or columns, writing migrations, writing insert/update/delete logic, repositories or DAOs, or describing storage in a spec or plan. Applies to Python (SQLAlchemy/Alembic) and Java (JPA/Flyway/Liquibase), even if the user only says "save it to the DB".
---

# Persistence policy

The database outlives the code. Schema and write rules protect data from bugs, re-runs and careless changes.

## Rules

1. **Schema changes only through versioned migrations.** Never auto-create or auto-alter schema at runtime (no `create_all()`, no `ddl-auto=update`).
2. **Never edit a committed migration.** Write a new one.
3. **Destructive changes need explicit human approval** recorded in the plan: dropping tables or columns, narrowing types, deleting data. Prefer expand-contract: add new, backfill, switch reads, remove old later.
4. **Natural keys get unique constraints.** Records from external sources (e.g. an arXiv ID) carry their source ID with a unique constraint.
5. **Idempotent writes.** Imports and jobs upsert on the natural key (`INSERT ... ON CONFLICT` / `MERGE`). Running a job twice never duplicates rows.
6. **Timestamps in UTC.** Every table has `created_at` and `updated_at` as timezone-aware types (`timestamptz` in Postgres).
7. **Transactions match business operations.** One unit of work per operation. Never hold a DB transaction open across an external HTTP call.
8. **No string-built SQL.** Parameterized queries only.
9. **No N+1 patterns.** Batch reads and writes instead of querying inside loops.
10. **Files live outside the database.** The DB stores path or URI plus metadata (size, checksum, timestamps).
11. **Data access sits in a repository layer.** Routes, controllers and business logic don't build queries.
12. **Every index has a reason.** Index columns used for lookups and filters; state which query each index serves.

## In a spec or plan

Include a **Data model** section: tables, columns and types, primary keys, unique constraints, indexes, the migration(s) to add, and retention or deletion rules.

## Tests required

- Run migrations against the real engine (Postgres in a container), not SQLite standing in for Postgres.
- Idempotency: run the write path twice, assert the same row count.
- Migrations upgrade cleanly from an empty database.

## Stack specifics

**Python:** SQLAlchemy 2.x (typed `Mapped[...]` models), Alembic for migrations, `psycopg` or `asyncpg` driver. Upsert via `sqlalchemy.dialects.postgresql.insert(...).on_conflict_do_update(...)`. Tests with `testcontainers` Postgres.

**Java:** Spring Data JPA with `spring.jpa.hibernate.ddl-auto=validate`, Flyway (or Liquibase) migrations. Upsert via a native `INSERT ... ON CONFLICT` query, since JPA `save()` is not an atomic upsert. Tests with Testcontainers Postgres.
