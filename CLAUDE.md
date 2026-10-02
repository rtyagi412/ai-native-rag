# arXiv RAG

Daily fetcher for recent cs.AI arXiv papers (metadata in Postgres, PDFs on disk).
Later intents add parsing, indexing and a RAG API. Current work: Requirements and designs live in specs/. .

## How work happens here
- Every change flows intent/ → specs/ → plans/ (same file name, e.g. 001-arxiv-fetcher.md).
- Implement only what the accepted plan says. If implementation must depart from
  the plan, update plans/<name>.md in the same commit and say why.
- Never edit intent/ or specs/ during implementation; flag disagreements instead.
- Cross-cutting rules (outbound HTTP, persistence, secrets/config) live in `.claude/skills/`.

## Stack
Python 3.12+, uv, asyncio throughout. httpx + tenacity, feedparser, SQLAlchemy 2.x
(async) + asyncpg + Alembic, Postgres 16, APScheduler 3.11.x (not 4.x), pydantic-settings,
tzdata (needed for `Asia/Kolkata` on Windows).
Tests: pytest, pytest-asyncio, respx, testcontainers (Docker must be running).

## Commands (created by the plan; may not exist yet)
- Install: `uv sync`
- Test: `make test` (all green; never skip or delete a failing test)
- Lint/format: `make lint` (ruff check + ruff format --check + mypy; zero errors)
- DB: `make db-up` (Postgres via docker compose), `make migrate` (alembic upgrade head)
- Run one fetch now: `make run-once`
- Run scheduler (daily 08:00 IST): `make run`

## Layout
- `src/fetcher/` app code: `settings.py`, `arxiv_client.py`, `rate_limiter.py`,
  `feed_parser.py`, `repository.py`, `pdf_store.py`, `jobs.py` (fetch + retention),
  `scheduler.py`, `cli.py`
- `migrations/` Alembic; `tests/unit/`, `tests/integration/`, `tests/fixtures/` (real arXiv responses)
- `data/pdfs/` default PDF directory (gitignored); `.env` is local and gitignored, `.env.example` is committed

## Conventions
- Type hints everywhere; mypy strict on src/.
- Logging: stdlib `logging`, key=value fields.
- Tests never call real external services; use recorded responses in tests/fixtures/.

## Verifying your work
Run `make lint` and `make test` before reporting any task complete, and paste the output.
If a test fails, fix the code, not the test.

## Things Claude gets wrong
(Empty for now. When Claude makes the same mistake twice, add the correction here.)
