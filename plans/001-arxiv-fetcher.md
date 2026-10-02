# Plan 001: arXiv paper fetcher

- **Spec:** specs/001-arxiv-fetcher.md (accepted). **Intent:** intent/001-arxiv-fetcher.md (accepted).
- **Skills to follow:** `.claude/skills/outbound-http`, `persistence`, `secrets-and-config`.
- **Greenfield:** the repo holds only CLAUDE.md, intent/, specs/, .claude/. No code exists. The directory is not yet a git repo.

## Context

Build the daily cs.AI fetcher described in the spec: APScheduler job at 08:00 Asia/Kolkata, rate-limited and retried arXiv traffic, metadata in Postgres, PDFs on disk, retention cleanup. The plan is executed autonomously, so each step is self-contained.

## Decisions made with Rahul while planning

| Topic | Decision |
|---|---|
| Git | Step 1 runs `git init`, adds `.gitignore`, first commit. One commit per step afterwards, ending with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. |
| `ARXIV_CONTACT` | Rahul approved using `tyagi.rahul.ind@gmail.com`. It goes ONLY in the local, gitignored `.env`. It never appears in committed files, fixtures, notes, logs or commit messages. `.env.example` uses `you@example.com`. |
| `make` on Windows | Write a Makefile as CLAUDE.md says. Step 1 runs `make --version`; if missing, STOP and ask Rahul to install it. No fallback scripts. |
| Fixtures | Real arXiv fixtures are committed (private repo). Before the repo is ever made public, licensing of arXiv metadata must be checked (spec section 11). |
| APScheduler misfire (T-21) | Suspected spec contradiction (see Risks R-1). Verified in step 3. If confirmed, STOP and ask; do not pre-decide a design. |

## Global rules for every step

1. Test-first: write the step's tests, run them, see them fail for the right reason, then write code.
2. Finish with `make lint` and `make test` both green. Paste the output in the report. Never skip, delete or weaken a failing test. Fix the code.
3. Docker must be running for DB tests (testcontainers). If it is not, STOP (stop condition S-3).
4. Unit tests never touch the real arXiv. Only step 2 makes live requests. Tests set explicit settings and never read `.env`.
5. Do not edit `intent/` or `specs/`. Departures from this plan: edit this file (`plans/001-arxiv-fetcher.md`) in the same commit and say why.
6. No secrets in code, tests, fixtures, docs, commit messages. Never log `DB_URL`.
7. Only httpx use is inside `ArxivClient` (the step 2 spike script is throwaway and not committed).
8. Dependencies: only those named in CLAUDE.md and the spec. `pytest-cov`, `freezegun`, etc. are NOT allowed without asking (S-4). Dev tools allowed: ruff, mypy, pytest, pytest-asyncio, respx, testcontainers (+ type stubs if mypy needs them; ask first if more than types-only).

## Human prerequisites (before the agent starts)

Consolidated from decisions and stop conditions below; nothing new is added.

1. `make`, `uv`, Python >= 3.12 and Git are installed on the Windows host (S-1).
2. Docker is running, for testcontainers and `make db-up` (S-3).
3. Network access to `export.arxiv.org` and `arxiv.org` for the step 2 spike only (at most 3 requests).
4. A local, gitignored `.env` with `ARXIV_CONTACT=tyagi.rahul.ind@gmail.com` (approved by Rahul) and a throwaway local `DB_URL`. Never committed (S-9).
5. Rahul is reachable at step 3 to decide the T-21 / APScheduler misfire design if the contradiction is confirmed (S-5). Step 17 is blocked until then.
6. Explicit approval from Rahul, at step 18 only, if a real end-to-end `make run-once` against arXiv is wanted.
## Steps

Notation: **Files** (C = created, M = modified), **Covers**, **Tests**, **Verify**. Every step's Verify also includes `make lint` and `make test`.

### Step 1: Project skeleton
- **Files (C):** `pyproject.toml` (uv, Python >=3.12; deps: httpx, tenacity, feedparser, sqlalchemy[asyncio], asyncpg, alembic, apscheduler>=3.11,<4, pydantic-settings, tzdata; dev: pytest, pytest-asyncio, respx, testcontainers[postgresql], ruff, mypy), `uv.lock`, `Makefile`, `docker-compose.yml` (postgres:16, volume, healthcheck, creds from env with dummy dev defaults, port 5432), `.gitignore` (`.env`, `.venv`, `data/pdfs/`, `__pycache__`, `.mypy_cache`, `.ruff_cache`, `.pytest_cache`), `.env.example` (placeholder; completed in step 4), `alembic.ini` + `migrations/env.py` (async env reading `DB_URL` via the settings module once it exists; until step 4 reads nothing and `make migrate` documents that it needs `DB_URL`), `migrations/versions/.gitkeep`, `src/fetcher/__init__.py`, `src/fetcher/cli.py` (stub `run-once` and `run` subcommands that log "not implemented" and exit 2, replaced in steps 16 and 17), `tests/{unit,integration,fixtures}/` with `conftest.py`, `tests/unit/test_smoke.py`.
- **Makefile targets:** `install` (uv sync), `test` (`uv run pytest`), `lint` (`ruff check`, `ruff format --check`, `mypy src`), `db-up` (`docker compose up -d --wait`), `migrate` (`uv run alembic upgrade head`), `run-once` (`uv run python -m fetcher.cli run-once`), `run` (`uv run python -m fetcher.cli run`).
- **Config:** ruff (line length 100, rules E,F,I,UP,B,ASYNC), mypy `strict = true` for `src/`, pytest `asyncio_mode = "auto"`, `testpaths = ["tests"]`, marker `integration` (needs Docker).
- **Order inside the step:** first run `git init` (stop S-9 if a `.git` already exists with unexpected content), `make --version` (S-1 if missing), `uv --version`, `docker info` (S-3 if Docker down), `python --version` >= 3.12.
- **Covers:** CLAUDE.md "Commands" and "Layout". No FR/NFR yet.
- **Tests:** `test_smoke.py` imports `fetcher` and asserts the package is importable.
- **Verify:** `make install`, `make lint`, `make test`, `make db-up` (container healthy), `make migrate` with a throwaway local `DB_URL` env var pointing at the compose DB (no migrations yet; must exit 0), `make run-once` (stub exits 2, expected). Commit.

### Step 2: Verification spike, live arXiv (spec section 11 "Step 0")
Runs before any production code. At most 3 requests, sequential, at least 3 s apart.
- **Files (C):** `tests/fixtures/arxiv_cs_ai_page.xml`, `tests/fixtures/NOTES.md` (spike findings, no headers, no contact email), optionally `tests/fixtures/arxiv_error.xml`. **(M)** this plan file: add section "Spike findings" with the results. The spike script lives in the scratchpad directory and is NOT committed.
- **Procedure:**
  1. Compute a `submittedDate` window of the last 7 days in GMT (`YYYYMMDDHHMM`). One call: `GET https://export.arxiv.org/api/query?search_query=cat:cs.AI+AND+submittedDate:[<start>+TO+<end>]&sortBy=submittedDate&sortOrder=descending&start=0&max_results=5`, User-Agent `ai-native-rag-arxiv-fetcher/0.1.0 (+<contact from local .env>)`, explicit timeouts, redirects NOT auto-followed on the first attempt so any HTTP to HTTPS redirect is observed. Save the raw body.
  2. At least 3 s later, one request to the PDF link from the fixture (`<link title="pdf">`). Record only: status, final host after redirects, `Content-Type`, `Content-Length`, first 5 bytes. Do not save the PDF.
  3. At least 3 s later (optional), one deliberately invalid query to capture a real error-entry feed. If it yields no error feed, T-10 uses a hand-built fixture labelled `SYNTHETIC` in its filename and header comment.
  4. Parse the fixture with `feedparser` in a scratch script. Record: how `arxiv:primary_category`, `arxiv:doi`, `arxiv:journal_ref`, `arxiv:comment`, multiple `category` tags and authors surface; the id form (`http://arxiv.org/abs/<id>v<n>`); date formats; PDF link form and host.
  5. Record whether `Retry-After` or rate headers appeared; whether `export.arxiv.org` is accepted for PDFs; observations relevant to page size.
- **Covers:** spec section 11 items 1-4; informs T-10, FR-5, NFR-2.
- **Tests:** none new. Fixture is verified by step 6 tests.
- **Verify:** fixture exists, is well-formed XML, contains at least 1 entry, contains no contact email (`grep` the fixtures dir for the email string must return nothing). `make lint`, `make test`. Commit.
- **Stop conditions here:** HTTPS unavailable or redirects somewhere unexpected (S-2); the API returns no entries for the window; feedparser drops the `arxiv:` fields (spec says it handles them; if not, S-2, do not swap parser silently).

### Step 3: Verification spike, offline library behaviors
Closes the "not settled by step 0" list. Uses small throwaway experiments, results written to this plan's "Spike findings".
- **Files (M):** this plan. A few small committed tests are allowed where they pin a behavior the code will depend on (`tests/unit/test_apscheduler_behavior.py`, `tests/integration/test_testcontainers_smoke.py`).
- **Checks:**
  1. testcontainers starts Postgres 16 on this Windows+Docker host, asyncpg connects, a session-scoped fixture pattern works with pytest-asyncio (add the shared `pg_url` fixture in `tests/conftest.py`).
  2. SQLAlchemy 2.x async `postgresql.insert(...).on_conflict_do_update(...)` with `RETURNING` works on asyncpg, including `text[]`/`jsonb` columns and `pg_try_advisory_lock` on a dedicated connection.
  3. tenacity async retry with a custom `wait` that returns `max(backoff, Retry-After)` works as the spec needs.
  4. **APScheduler misfire semantics.** With `AsyncIOScheduler` and the default memory job store, determine: (a) what happens to a `CronTrigger` whose fire time passed while the scheduler was not running, then `start()` is called inside the grace window; (b) what `misfire_grace_time` and `coalesce` do for a job whose `next_run_time` is in the past at start. Determine this with no real waiting (use `add_job(next_run_time=<past>)`, or inspect `trigger.get_next_fire_time` and `scheduler.get_jobs()`).
  5. Can the process TZ be varied on this Windows host for T-7 (`TZ` env var in a subprocess honored by the C runtime; `time.tzset` does not exist on Windows)?
- **Covers:** spec section 11 "confirm early" bullets (except Retry-After and page size, done in step 2).
- **Outcome rules:** if 4(a) shows a missed 08:00 is NOT recovered after restart (expected), **STOP (S-5)** and report to Rahul with the evidence and options (last-run record plus startup catch-up needing a new table; or persistent job store needing an extra driver). Steps 4 to 15 do not depend on that answer and may proceed only if Rahul says so; steps 16 and 17 are blocked until the spec is amended. If 5 shows TZ cannot be varied, plan T-7 as aware-datetime computation for several `now` zones plus a subprocess check where possible, and record this as a plan departure.
- **Verify:** `make lint`, `make test` (integration tests need Docker). Commit.

### Step 4: Settings
- **Files (C):** `src/fetcher/settings.py`, `tests/unit/test_settings.py`. **(M)** `.env.example` (every key from spec section 6 with dummy values and a comment on units; `DB_URL=postgresql+asyncpg://user:password@localhost:5432/arxiv`, `ARXIV_CONTACT=you@example.com`), `migrations/env.py` (read `DB_URL` through `Settings`).
- **Design:** one `Settings(BaseSettings)`, `env_file=".env"`, `DB_URL: SecretStr` required, `ARXIV_CONTACT` required, all other names/types/defaults exactly per spec section 6. Validators: `ARXIV_MIN_INTERVAL_SECONDS >= 3.0`, `FETCH_WINDOW_DAYS >= 1`, positive ints for caps and attempts, `SCHEDULE_TZ` must resolve via `ZoneInfo`. `get_settings()` cached accessor. Helper `safe_db_target()` returns host/dbname only. This is the only module reading env.
- **Covers:** NFR-5, NFR-2/3 configurability, spec section 6.
- **Tests (first):** T-14 (missing `DB_URL`, missing `ARXIV_CONTACT`, interval 2.9 rejected, `repr(settings)` and `str(settings)` hide `DB_URL`, error text from validation does not leak the URL, defaults match spec table, `.env` not read when tests pass `_env_file=None`).
- **Verify:** `uv run pytest tests/unit/test_settings.py`, then lint and test. Commit.

### Step 5: Logging helper and RateLimiter
- **Files (C):** `src/fetcher/logging_utils.py` (key=value formatter helper `log_kv(logger, level, event, **fields)`; values quoted if they contain spaces; refuses/masks keys named like secrets), `src/fetcher/rate_limiter.py`, `tests/unit/test_rate_limiter.py`, `tests/unit/test_logging_utils.py`.
- **Design:** `RateLimiter(min_interval, clock=time.monotonic, sleep=asyncio.sleep)`; `async acquire()` holds an `asyncio.Lock` across the wait so callers serialize (also gives single-connection ordering); returns an object/tuple with `gap_since_previous_ms` (None for the first request) and `monotonic_start`. Records the send time after the wait.
- **Covers:** NFR-3 (limiter part), FR-13 (gap measurement).
- **Tests (first):** T-11 limiter parts: spacing >= interval on a fake clock, first call does not wait, two concurrent callers are serialized, interval is measured between send times (not between completions), no real sleeps.
- **Verify:** pytest on the two files, lint, test. Commit.

### Step 6: Feed parser
- **Files (C):** `src/fetcher/feed_parser.py` (`PaperMeta` frozen dataclass, `parse_feed(text) -> ParsedFeed(entries, skipped, total_results)`, `ArxivErrorFeed` exception), `tests/unit/test_feed_parser.py`. **(C, only if no real one was captured)** `tests/fixtures/SYNTHETIC_arxiv_error.xml`; additional small hand-edited variants derived from the real fixture for malformed-entry cases, labelled `SYNTHETIC`.
- **Design:** versionless `arxiv_id` (handles `2501.01234v2` and old-style `cs/0501001v1`), `version` int, whitespace-normalized title and abstract, ordered authors, `primary_category`, all `categories`, `published_at` and `source_updated_at` as UTC-aware datetimes, DOI/journal_ref/comment optional, `abs_url`, `pdf_url` from `<link title="pdf">` (fall back to constructing `.../pdf/<id>v<n>` only if the real fixture shows that is the pattern; otherwise skip the entry as malformed). Error entry (arXiv returns an Atom entry whose id is under `/api/errors`) raises `ArxivErrorFeed`. A malformed entry is skipped with WARNING and counted.
- **Covers:** FR-5 (parse side), spec section 7 (error entry, malformed entry).
- **Tests (first):** T-10 (real fixture: categories, dates, id stripped, PDF link, authors; error feed), malformed-entry skipped while others parse (parser side of T-18). Tests read fixtures as static data and do not depend on today's date.
- **Verify:** pytest, lint, test. Commit.

### Step 7: ArxivClient request core (timeouts, retries, classification, logging)
- **Files (C):** `src/fetcher/arxiv_client.py` (core part), `tests/unit/test_arxiv_client_retry.py`.
- **Design:** class `ArxivClient(settings, limiter=None, client=None, clock/sleep injectable, rng injectable)`; owns one `httpx.AsyncClient` with `httpx.Limits(max_connections=1, max_keepalive_connections=1)`, `httpx.Timeout` per spec section 4, User-Agent `ai-native-rag-arxiv-fetcher/<version> (+<ARXIV_CONTACT>)`; `aclose()`. Internal `_request(kind, url, params)` performs each attempt: acquire limiter, emit `arxiv_request` INFO line (UTC send timestamp, monotonic start, `gap_since_previous_request_ms`, kind, attempt, status, elapsed_ms; ERROR if gap < interval), classify (timeouts/transport errors, 429, 500/502/503/504 retry; other 4xx fail fast with `ArxivPermanentError`; retries exhausted raise `ArxivTransientError` after logging service, endpoint, status, attempts, elapsed). tenacity: max `ARXIV_RETRY_MAX_ATTEMPTS`, `wait_random_exponential` base `ARXIV_RETRY_BASE_SECONDS`, factor 2, total-wait cap `ARXIV_MAX_TOTAL_WAIT_SECONDS`, wait at least `Retry-After` (seconds or HTTP-date; capped by total wait cap, and if `Retry-After` exceeds the remaining cap the call fails as exhausted rather than sleeping past the cap). Limiter acquired once per attempt, so retries count.
- **Covers:** NFR-2, NFR-3, FR-13, NFR-5 (no auth/secrets in logs; no bodies logged).
- **Tests (first), all with respx and fake clock/sleep:** T-11 (503 then 200 succeeds; 404 not retried; `Retry-After` honored; retries exhausted raises; spacing >= 3 s including retries; concurrent callers serialized), T-19 (429 with `Retry-After` retried; 400 and 404 fail fast), timeouts and transport errors retried, User-Agent header present and contains the contact, `arxiv_request` log line carries every required field, a gap below the interval logs ERROR (inject a limiter with a smaller interval for this test only).
- **Verify:** pytest, lint, test. Commit.

### Step 8: ArxivClient search and PDF download, plus PdfStore
- **Files (M):** `src/fetcher/arxiv_client.py`. **(C):** `src/fetcher/pdf_store.py`, `tests/unit/test_arxiv_client_search.py`, `tests/unit/test_arxiv_client_pdf.py`, `tests/unit/test_pdf_store.py`.
- **Design:**
  - `search_cs_ai(start, max_results, window_start, window_end) -> ParsedFeed`: builds `cat:cs.AI AND submittedDate:[YYYYMMDDHHMM TO YYYYMMDDHHMM]` (GMT, converted from aware datetimes regardless of host TZ), `sortBy=submittedDate`, `sortOrder=descending`; parses through `feed_parser`; an error-entry feed raises a non-retryable `ArxivQueryError`.
  - `download_pdf(url, dest_tmp: Path)`: streams in chunks to the temp file, per-chunk read timeout `PDF_READ_TIMEOUT_SECONDS`, overall cap `PDF_TOTAL_TIMEOUT_SECONDS` (via `asyncio.timeout`, counts as a retryable timeout), same retry/limiter/log path (kind `pdf`), temp file removed on any failure, returns bytes written.
  - `PdfStore(root)`: `path_for(arxiv_id, version, year)` -> `<yyyy>/<id with "/" -> "_">v<version>.pdf` relative; `finalize(tmp, rel_path)` checks `%PDF-` magic, computes SHA-256 and size, atomically renames (`os.replace`), raises `NotAPdfError` and deletes the temp file otherwise; `delete(rel_path) -> bool` (missing file returns False, not an error); creates parent dirs; rejects path traversal.
- **Covers:** FR-2 (query shape), FR-6 (download, verify), FR-14 (query side), NFR-4 (atomic write), NFR-2/3 for PDFs, spec section 7 (non-PDF body, error entry).
- **Tests (first):** T-20 (query side: correct GMT range for a fixed clock and a non-UTC host TZ setting; request sorted by submittedDate desc; paging params), T-12 (HTML body rejected, temp removed), T-10 error-entry through the client, PDF 404 fails fast, PDF timeout then success, SHA-256 and size correct, atomic rename leaves no partial file when the stream fails mid-way, path traversal rejected, `delete` of a missing file tolerated (feeds T-6).
- **Verify:** pytest, lint, test. Commit.

### Step 9: DB models, session, migration 0001
- **Files (C):** `src/fetcher/db.py` (async engine and `async_sessionmaker` factory from `Settings`, `dispose()`), `src/fetcher/models.py` (typed `Mapped[...]` `Paper` model, `Base`), `migrations/versions/0001_create_papers.py`, `tests/integration/test_migration.py`.
- **Design:** exactly the spec section 5 table, constraints and indexes: `UNIQUE (arxiv_id)`, CHECK on `pdf_status`, partial index `(created_at) WHERE pdf_status IN ('pending','failed')`, partial index `(pdf_downloaded_at) WHERE pdf_status = 'downloaded'`, `created_at`/`updated_at` `timestamptz` default `now()`. `updated_at` is set explicitly on every write in the repository (and `onupdate` in the model as a backstop). No `create_all()` anywhere. Downgrade drops the table (dev only; the agent never runs downgrade, see S-7). Migration is hand-written (do not rely on autogenerate output unreviewed).
- **Covers:** FR-5 storage, NFR-7, persistence skill rules 1, 2, 4, 6, 12.
- **Tests (first):** T-13 (upgrade on an empty testcontainers Postgres cleanly; duplicate `arxiv_id` rejected; bad `pdf_status` rejected; NOT NULL columns enforced; the two partial indexes exist with the right predicates; column types match, e.g. `categories` is `text[]`, `authors` is `jsonb`, timestamps are `timestamptz`; the model metadata matches the migrated schema, i.e. an Alembic autogenerate diff is empty).
- **Verify:** `uv run pytest tests/integration/test_migration.py`; with local Docker DB: `make db-up` then `make migrate` against a throwaway `DB_URL` env var (upgrade only). lint, test. Commit.

### Step 10: PaperRepository and advisory lock
- **Files (C):** `src/fetcher/repository.py`, `tests/integration/test_repository.py`.
- **Design (all SQL lives here, parameterized, one short transaction per method):**
  - `existing_ids(ids) -> set[str]` single query `WHERE arxiv_id = ANY(:ids)`.
  - `upsert_paper(meta, now)`: `INSERT ... ON CONFLICT (arxiv_id) DO UPDATE` metadata fields and `updated_at`; never regresses `pdf_status` from `downloaded`/`expired`; never touches `pdf_downloaded_at`, `pdf_path`, `pdf_attempts`; new rows get `pdf_status='pending'`. Returns the row id and whether it was inserted.
  - `mark_pdf_downloaded(arxiv_id, path, size, sha256, now)`, `mark_pdf_failed(arxiv_id, now)` (increments `pdf_attempts`), `list_pdf_retry(max_attempts, limit)` (status pending/failed and attempts < max, oldest `created_at` first), `count_exhausted_retries(max_attempts)` or a method returning exhausted ids so the job can log the one-time WARNING, `list_expired(cutoff)`, `mark_pdf_expired(ids, now)` (sets status, clears `pdf_path`, sets `pdf_expired_at`, keeps size and sha256).
  - Advisory lock: `AdvisoryLock` async context manager using `pg_try_advisory_lock(key)` on a dedicated connection held for the whole run and `pg_advisory_unlock` on exit; fixed key constant. It uses a dedicated connection that is not part of any open transaction (a held connection is not a held transaction; it must not wrap HTTP in a transaction).
  - There is intentionally no method that deletes from `papers`.
- **Covers:** FR-5, FR-9 (data side), FR-11 (lock primitive), NFR-4, NFR-7, persistence rules 5, 7, 8, 9, 11.
- **Tests (first):** T-2 (repository part: upsert twice gives one row; second upsert updates title but a `downloaded` row stays `downloaded` with the same `pdf_downloaded_at`), existence check returns the right subset and uses one query, `list_pdf_retry` ordering/limit/attempt filter, `mark_pdf_failed` increments, expired marking keeps metadata, size and sha256, lock part of T-15 (a second connection cannot take the lock while the first holds it; it can after release; lock released if the body raises). A grep-style test asserts `repository.py` is the only module importing `sqlalchemy` query constructs (simple import check over `src/fetcher`).
- **Verify:** pytest, lint, test. Commit.

### Step 11: RetentionJob
- **Files (C):** `src/fetcher/retention.py` (`RetentionJob`), `tests/integration/test_retention.py`.
- **Design:** `run(now) -> RetentionResult(expired, missing, failed_deletions)`. Cutoff `now - PDF_RETENTION_DAYS`. `list_expired` -> for each: `PdfStore.delete`; success or already-missing (INFO) -> mark row `expired`; permission error -> WARNING, row left `downloaded`, continue. Clock injected (no wall clock in tests).
- **Covers:** FR-8, spec section 7 retention rows, spec "Retention".
- **Tests (first):** T-5 (rows downloaded 31 and 29 days ago, fixed clock: only the old file is deleted and its row is `expired`), T-6 (both rows still exist with metadata intact; a missing file is tolerated and the row still marked `expired`; delete failure leaves the row `downloaded`; test that `PaperRepository` exposes no delete-row method).
- **Verify:** pytest, lint, test. Commit.

### Step 12: FetchJob core path (single page, new papers, cap)
- **Files (C):** `src/fetcher/jobs.py` (`FetchJob`, `RunSummary`, `RunClock`), `tests/integration/test_fetch_job.py`, `tests/integration/conftest.py` helpers (respx feed builder from the real fixture, fake PDF bodies, tmp `PDF_DIR`, settings factory).
- **Design:** `FetchJob(settings, client, repo, pdf_store, clock, retention)`; `run(run_id) -> RunSummary`. Steps per spec section 3: search page, `existing_ids` batch, take unseen in feed order up to budget, for each new paper: upsert (committed) -> download PDF to temp (no transaction open) -> finalize -> `mark_pdf_downloaded`. Enforce the cap `FETCH_MAX_PAPERS`. 0 to 4 new papers is success with INFO. Client-side window filter on `published_at` is added in step 13; retention wired in step 15.
- **Covers:** FR-2, FR-3 (new-paper side), FR-5, FR-6, FR-7, NFR-4, NFR-7, persistence rule 7.
- **Tests (first):** T-1 (7 unseen entries: exactly 5 rows, the 5 newest, each `downloaded`, file exists with matching size and SHA-256), T-2 (job twice: row count unchanged, PDFs not re-downloaded, verified by respx call counts), T-3 (all stored: success, no error logs), T-4 (3 unseen: stores 3, success, no page requested beyond what is needed). A test asserts no DB transaction is open during an HTTP call (e.g. `pg_stat_activity` `state` is not `idle in transaction` observed from inside a respx side effect).
- **Verify:** pytest, lint, test. Commit.

### Step 13: Paging and recency window
- **Files (M):** `src/fetcher/jobs.py`; **(M)** `tests/integration/test_fetch_job.py` (or new `test_fetch_job_paging.py`).
- **Design:** loop pages while budget > 0 and `pages < ARXIV_MAX_PAGES` and the feed is not exhausted (page shorter than `ARXIV_PAGE_SIZE` or `start >= totalResults`); `start += ARXIV_PAGE_SIZE`. Window `[now - FETCH_WINDOW_DAYS, now]` in UTC computed from the injected clock, sent to arXiv, and enforced client-side on `published_at` (entries outside are ignored; because results are sorted descending, an entry older than the window ends paging).
- **Covers:** FR-2, FR-4, FR-14.
- **Tests (first):** T-9 (first page fully stored, second page has new entries, stops at cap; stops at `ARXIV_MAX_PAGES`; stops on exhaustion), T-20 (job side: request carries the right GMT range for a fixed clock; an older-than-window entry returned by the mock is ignored; only-older papers means nothing stored and success).
- **Verify:** pytest, lint, test. Commit.

### Step 14: Per-paper failure isolation and PDF retry set
- **Files (M):** `src/fetcher/jobs.py`, `src/fetcher/repository.py` if a helper is missing; tests in `tests/integration/test_fetch_job_failures.py`.
- **Design:** retry set loaded first (`list_pdf_retry`, oldest first, limited to cap, not subject to the window), budget = cap minus retry-set size; retry successes mark `downloaded`, failures `mark_pdf_failed`; papers reaching `PDF_MAX_ATTEMPTS` stay `failed` and log a WARNING once per run. Each paper's work is wrapped so metadata errors, DB errors, `ArxivPermanentError`, `ArxivTransientError`, `NotAPdfError` are logged (ERROR with arXiv ID for DB errors, WARNING for PDF failures), the unit rolled back, and the loop continues.
- **Covers:** FR-3 (cap includes retries), FR-9, FR-10, spec section 7 rows (PDF fails after retries, not a PDF, DB error on a paper).
- **Tests (first):** T-8 (first run PDF 503 x3 gives `failed` row with `pdf_attempts=1`; next run retries and gets `downloaded`; retry counts toward the cap, e.g. cap 5 with 2 retries leaves budget 3), T-18 (one malformed entry and one PDF 404: others stored, run succeeds), attempts exhausted at `PDF_MAX_ATTEMPTS` are no longer retried and warn, a simulated DB error for one paper does not abort the rest.
- **Verify:** pytest, lint, test. Commit.

### Step 15: Run-level behavior (lock, API failure, summary, retention wiring, timing audit)
- **Files (M):** `src/fetcher/jobs.py`; **(C)** `tests/integration/test_fetch_job_run_level.py`.
- **Design:** acquire `AdvisoryLock` at the start (not obtained: INFO, return a `RunSummary` flagged `skipped_locked`, success); DB unavailable at start aborts with ERROR; an API query failure after retries (or an arXiv error entry) ends the run with a run-level error: `RunSummary.status="error"`, nothing partial left corrupt (already-committed rows stay valid and retried next run); `RetentionJob` runs after fetching, also after a run-level API failure (it does not touch arXiv); one INFO `run_summary` line with run_id, retried, new, downloaded, failed, expired, pages, duration_ms; the lock is always released.
- **Covers:** FR-7, FR-8 (wired), FR-11, NFR-6 (informational timing assertion on a fake clock: a 5-paper run issues about 1-3 API calls and 5 PDFs at 3 s spacing), spec section 7 rows (API fails, DB unavailable, lock held), NFR-5 (no `DB_URL` text in any captured log across the run).
- **Tests (first):** T-15 (job level: while one run holds the lock a second run returns without any HTTP call), T-16 case 1 (API 503 x2 then 200, PDF times out once then succeeds, all 5 papers stored), T-16 case 2 (outage longer than the retry budget: run ends with error, nothing corrupt stored, a following run with the outage over recovers and stores the papers), T-17 (full multi-request job with fake clock and captured logs: every `arxiv_request` record has `gap_since_previous_request_ms` >= 3000 including retried attempts and the API-to-PDF transition; a deliberately broken limiter, e.g. interval 0, makes the same audit helper fail), log-hygiene test (captured logs contain neither the full `DB_URL` nor the password).
- **Verify:** pytest, lint, test. Commit.

### Step 16: CLI `run-once`
- **Files (M):** `src/fetcher/cli.py`; **(C)** `tests/integration/test_cli.py`.
- **Design:** `python -m fetcher.cli run-once` builds settings (fail fast with masked errors, non-zero exit), logging config (`LOG_LEVEL`, stdlib, key=value), engine, `ArxivClient`, then calls the same `FetchJob.run` used by the scheduler (shared factory `build_job(settings)` in `jobs.py` or `app.py`); exit code 0 on success including 0 to 4 new papers and lock-held skip; non-zero on run-level failure; always closes the client and disposes the engine. Entry point `fetcher = "fetcher.cli:main"` in `pyproject.toml`.
- **Covers:** FR-12, FR-7 (exit status), spec section 7 (invalid setting refuses to start, API failure exit non-zero).
- **Tests (first):** exit 0 on a normal run and on 0 new papers, exit non-zero on API failure and on missing `DB_URL`, the CLI and scheduler call the same function (assert via the shared factory), no `DB_URL` in output.
- **Verify:** pytest, lint, test; `make run-once` with a local `.env` containing a throwaway test DB and `ARXIV_BASE_URL` pointed at an unroutable local address is NOT used; instead verify via the tests (the agent never hits real arXiv after step 2 except as noted in step 18). Commit.

### Step 17: Scheduler
**Blocked until step 3's APScheduler finding (S-5) is resolved by Rahul if the contradiction was confirmed.** Implement the resolved design; the baseline below covers the parts that are not in question.
- **Files (C):** `src/fetcher/scheduler.py`, `tests/unit/test_scheduler.py`; **(M)** `src/fetcher/cli.py` (`run` subcommand).
- **Design:** `build_scheduler(settings, job_callable)` returns an `AsyncIOScheduler` with `CronTrigger(hour=SCHEDULE_HOUR, minute=SCHEDULE_MINUTE, timezone=ZoneInfo(SCHEDULE_TZ))`, `max_instances=1`, `coalesce=True`, `misfire_grace_time=SCHEDULE_MISFIRE_GRACE_SECONDS`, and a job wrapper that catches and logs all exceptions so the scheduler stays alive. `run` starts the scheduler, installs signal handling (SIGINT; on Windows use `KeyboardInterrupt`/`asyncio` cancellation), shuts down cleanly and closes the client and engine. A run-level error does not stop the scheduler.
- **Covers:** FR-1, FR-11 (in-process `max_instances=1`), FR-12 (shared code path), NFR-1.
- **Tests (first):** T-7 (next fire time is 08:00 Asia/Kolkata = 02:30 UTC for several reference `now` values, with the process TZ varied via the mechanism chosen in step 3 and also with aware `now` in `UTC` and `America/New_York`; asserts `max_instances=1` and the trigger carries an explicit tzinfo, not the OS zone), T-21 (the behavior resolved in step 3 / by Rahul: job runs exactly once when started within the grace window after a missed 08:00, not at all beyond it, with fake time and no real waiting), a wrapper test that an exception in the job is logged and the scheduler job remains scheduled.
- **Verify:** pytest, lint, test; `make run` smoke: start, confirm the log shows the next run time in IST, stop with Ctrl+C (manual, short, no arXiv call). Commit.

### Step 18: Final hardening and acceptance
- **Files (M):** docs touch-ups only if required: CLAUDE.md "Things Claude gets wrong" only if a repeated mistake occurred; plan file "Spike findings" and a "Deviations" section.
- **Work:** run the whole suite twice (flake check), `make lint`, confirm `git status` clean, `.env` untracked, `grep -r` for the contact email and for password-like strings in tracked files returns nothing, confirm coverage table below is satisfied by listing every T-ID's test name, run one real end-to-end `make run-once` ONLY if Rahul explicitly approves it at that point (live traffic, up to about 1 API call plus 5 PDFs); otherwise record it as not performed.
- **Covers:** S1-S5 acceptance cross-check, NFR-5, NFR-6.
- **Verify:** `make lint`, `make test` (paste full output). Commit.

## Coverage table

| Item | Step(s) |
|---|---|
| FR-1 | 17 |
| FR-2 | 8 (query), 12, 13 |
| FR-3 | 12 (cap), 14 (retries count) |
| FR-4 | 13 |
| FR-5 | 6 (parse), 9, 10, 12 |
| FR-6 | 8, 12 |
| FR-7 | 12, 15, 16 |
| FR-8 | 11, 15 (wired) |
| FR-9 | 14 |
| FR-10 | 14 |
| FR-11 | 10 (lock), 15 (job), 17 (`max_instances`) |
| FR-12 | 16, 17 |
| FR-13 | 5, 7, 15 |
| FR-14 | 8 (query), 13 |
| NFR-1 | 17 |
| NFR-2 | 7, 8 |
| NFR-3 | 5, 7 |
| NFR-4 | 8 (atomic), 10, 12 |
| NFR-5 | 4, 7, 15 |
| NFR-6 | 15 (informational), 18 |
| NFR-7 | 9, 10 |
| T-1 | 12 |
| T-2 | 10 (repo), 12 (job) |
| T-3 | 12 |
| T-4 | 12 |
| T-5 | 11 |
| T-6 | 11 |
| T-7 | 17 |
| T-8 | 14 |
| T-9 | 13 |
| T-10 | 6 (parser, real fixture), 8 (error entry via client) |
| T-11 | 5 (limiter), 7 (retry) |
| T-12 | 8 |
| T-13 | 9 |
| T-14 | 4 |
| T-15 | 10 (primitive), 15 (job) |
| T-16 | 15 |
| T-17 | 15 (client-level pieces in 7) |
| T-18 | 6 (parser), 14 (job) |
| T-19 | 7 |
| T-20 | 8 (query), 13 (job) |
| T-21 | 17 (after S-5 resolution) |
| Spec section 11 items | 2 (live), 3 (offline) |
| Intent S1-S5 | S1: 12; S2: 15; S3: 15; S4: 12; S5: 11 |

## Configuration (secrets-and-config)

Implemented exactly as spec section 6 (step 4). Only secret: `DB_URL` (`SecretStr`, no default, never logged). `.env.example` is updated in the same step that adds a setting (all keys land in step 4; if any later step needs a new setting, STOP per S-4/S-8 since the spec lists them all).

## Risks

**What this could break:** nothing existing (greenfield). External risk: violating arXiv's usage terms and getting blocked. Mitigations: one limiter shared by API and PDFs, single connection, minimum interval validated at >= 3.0, the live spike limited to 3 requests, tests fully mocked.

| ID | Risk |
|---|---|
| R-1 | **Spec/reality mismatch on T-21.** APScheduler 3.x with an in-memory job store does not remember a missed 08:00 across process restarts, so `misfire_grace_time` alone cannot satisfy "down at 08:00, restart within 1 h, runs once". Verified in step 3. Resolution needs Rahul and a spec amendment. |
| R-2 | **T-7 on Windows.** `time.tzset` does not exist on Windows, so "process TZ set to another zone" may not be directly testable; fallback is aware-datetime computation plus a subprocess `TZ` check. |
| R-3 | **Docker/testcontainers on Windows** may be slow or flaky; many tests are integration. Use a session-scoped container and per-test table truncation (test-only truncation of the throwaway container is not a destructive change to real data). |
| R-4 | **feedparser vs `arxiv:` extension tags.** Verified in step 2; fall back requires asking (S-2). |
| R-5 | **Cap includes retries** means a few permanently failing PDFs can crowd out new papers for up to `PDF_MAX_ATTEMPTS` runs (accepted in the spec). |
| R-6 | **Windows file semantics:** `os.replace` on an existing destination and deleting open files can raise; tests cover rename and delete errors. |
| R-7 | **Fixture licensing** (arXiv metadata in a repo). Private for now; check before publishing. |

**Riskiest step: Step 15 (run-level behavior)**, followed closely by step 17. Step 15 combines the advisory lock on a long-held connection, outage recovery (T-16) and the timing audit (T-17) across every earlier component; a bug in the limiter or retry composition only surfaces here. Step 17 is risky because of R-1 and R-2. Step 3 exists to surface R-1 and R-2 early.

**Alternatives considered and rejected:**
- Hand-parsing Atom with `xml.etree` instead of `feedparser`: more code, spec chose feedparser (fall back only if step 2 disproves it, with approval).
- `aiolimiter` or a token bucket instead of the custom min-interval limiter: the skill specifies the min-interval limiter with injectable clock; token bucket would permit bursts, which arXiv forbids.
- `freezegun` for time in tests: rejected, not in the allowed dependency list; clocks are injected instead.
- APScheduler `SQLAlchemyJobStore` for restart-safe scheduling: needs a sync driver and extra dependency; left to Rahul's decision under R-1.
- One big FetchJob step: rejected; split into steps 12 to 15 to keep commits small and reviewable.
- SQLite for DB tests: rejected by the persistence skill (must be real Postgres).

## Stop conditions

The implementing agent must stop and ask Rahul (report what was found, with evidence, and wait) when:

- **S-1** `make`, `uv`, Python >= 3.12 is missing, or `git init` finds an existing repo it did not expect.
- **S-2** The spike (step 2) contradicts the spec: HTTPS or the API URL does not work, redirects go somewhere unexpected, PDF link form or host differs materially from the spec, `feedparser` loses `arxiv:` fields, or arXiv returns 403/429 to a single polite request. Do not retry in a loop. Do not make more than 3 live requests in step 2.
- **S-3** Docker is not running or testcontainers cannot start Postgres.
- **S-4** A dependency not named in CLAUDE.md or the spec is needed (including test helpers like `freezegun`), or a new setting is needed.
- **S-5** Step 3 confirms the APScheduler misfire contradiction (R-1), or any other spec requirement cannot be met with the specified components.
- **S-6** A test cannot pass without changing the spec, the test's intent or its assertion. Fix code, never the test; if the spec itself is wrong, stop.
- **S-7** Any destructive change: running `alembic downgrade`, dropping tables or columns, deleting rows from `papers` or any data outside a throwaway testcontainers DB or `tmp_path`, `git reset --hard`, force-push, deleting files not created by the plan.
- **S-8** The plan needs to depart in a way that changes behavior (not just a detail): update the plan file with the reason, and stop if it touches an FR/NFR/T.
- **S-9** A secret or the contact email is about to be committed, appears in a tracked file or log output, or `.env` shows as tracked. If it reached git history, flag it for rotation; do not just delete the commit.
- **S-10** The same step fails `make lint` or `make test` after 3 genuine fix attempts, or a live-traffic action beyond step 2 (or the explicit approval in step 18) would be needed.
- **S-11** Any need to run real arXiv requests outside step 2 and step 18.

## Definition of done

1. Steps 1 to 18 are complete, each in its own commit with `make lint` and `make test` green (output pasted in the report).
2. Every T-ID in the spec (T-1 to T-21) has a passing automated test, mapped as in the coverage table; no skipped, xfailed or deleted tests.
3. `make lint` has zero errors (ruff check, ruff format --check, mypy strict on `src/`).
4. All CLAUDE.md commands work: `make install`, `test`, `lint`, `db-up`, `migrate`, `run-once`, `run`.
5. Migration `0001_create_papers` applies to an empty Postgres 16; no `create_all()` anywhere; `papers` has no delete path in code.
6. `.env.example` lists every setting from spec section 6 with dummy values; `.env` is untracked; no secret or contact email in tracked files, fixtures, logs or commit messages.
7. Fixtures from the real arXiv spike are committed with notes; synthetic fixtures are labelled.
8. T-21 and the misfire behavior are resolved as Rahul decided (or recorded as explicitly deferred by Rahul).
9. The plan file contains "Spike findings" and "Deviations" sections, updated for anything that differed from this plan.
10. Intent success criteria S1 to S5 are demonstrably covered by T-1/T-2, T-16, T-17, T-2, T-5/T-6.
11. Final report lists anything not done (e.g. the optional live end-to-end run) plainly.

