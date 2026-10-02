# Spec 001: arXiv paper fetcher

- **Status:** accepted
- **Intent:** [intent/001-arxiv-fetcher.md](../intent/001-arxiv-fetcher.md) (status: accepted)
- **Skills applied:** `outbound-http`, `persistence`, `secrets-and-config` (all three are relevant: arXiv calls, Postgres writes, settings/DB credentials)
- **Stack:** Python 3.12+, async
- **Decisions confirmed with Rahul before writing:** in-process APScheduler; retention counted from PDF download time (30 days); a failed PDF keeps the metadata row and is retried next run; "cs.AI" means any paper listing cs.AI (cross-lists included).

## 1. Traceability

| Intent item | Covered by |
|---|---|
| Proposed outcome: daily at 08:00 IST | FR-1, NFR-1 |
| Proposed outcome: up to 5 most recent cs.AI papers not already stored | FR-2, FR-3, FR-4, FR-14 |
| Proposed outcome: metadata in Postgres, PDFs on disk | FR-5, FR-6 |
| Proposed outcome: fewer than 5 is normal | FR-7 (T-3, T-4) |
| Proposed outcome: failed calls retried | NFR-2, FR-9 |
| Proposed outcome: all arXiv traffic rate-limited | NFR-3 |
| Proposed outcome: PDFs older than 1 month removed | FR-8 |
| Constraint C1: at most 1 request / 3 s, API and PDFs | NFR-3, FR-13 |
| Constraint C2: transient failures (timeout, 5xx, 429) retried with exponential backoff and limit; other 4xx not retried | NFR-2 |
| Constraint C3: re-running creates no duplicates | NFR-4, FR-5, FR-11 |
| Constraint C4: one failed paper does not fail the run; logged and skipped | FR-10 |
| Constraint C5: Python in-process scheduler, not Airflow | FR-1, FR-12 |
| Constraint C6: runs 08:00 IST (Asia/Kolkata), independent of server TZ | FR-1, NFR-1 |
| Constraint C7: PDFs kept 1 month then deleted; metadata stays | FR-8, Data model retention rules |
| Success S1: daily run stores up to 5 new papers, each with PDF | FR-2..FR-6, FR-9; T-1 |
| Success S2: simulated arXiv outage triggers retries and the run recovers | NFR-2, FR-9; T-16 |
| Success S3: request timing logs show no two arXiv calls closer than 3 s | NFR-3, FR-13; T-11, T-17 |
| Success S4: running twice in a row adds no duplicates | NFR-4; T-2 |
| Success S5: PDFs older than 1 month deleted, rows remain | FR-8; T-5, T-6 |

Every constraint and Success line is traced directly. "Fewer than 5 is normal" is no longer a Success line but remains in Proposed outcome, so it keeps its tests.

## 2. Requirements

### Functional
- **FR-1** A scheduler inside the long-running process triggers the job daily at 08:00 in `Asia/Kolkata`, regardless of host timezone. The timezone is set explicitly on the trigger, never inherited from the OS.
- **FR-2** Each run queries arXiv for `cat:cs.AI` restricted to a recency window (FR-14), sorted by `submittedDate` descending, in pages, and collects papers whose versionless arXiv ID is not in the database.
- **FR-3** A run processes at most `FETCH_MAX_PAPERS` (default 5) papers in total. This cap includes PDF-retry papers (FR-9).
- **FR-4** Paging stops when the cap is reached, the feed is exhausted, or `ARXIV_MAX_PAGES` is reached.
- **FR-5** For each new paper, upsert metadata on `arxiv_id`: title, abstract, authors, primary and all categories, published/updated dates, DOI, journal ref, comment, abs URL, PDF URL.
- **FR-6** Download each new paper's PDF to `PDF_DIR`, verify it, and record path, size, SHA-256 and download time in the paper's row.
- **FR-7** Finding 0 to 4 new papers is a normal outcome: exit status success, INFO log, no alert.
- **FR-8** After fetching, delete PDF files whose `pdf_downloaded_at` is older than `PDF_RETENTION_DAYS` (default 30). Mark the row `pdf_status='expired'`, clear `pdf_path`, and never delete the metadata row. A file already missing is not an error.
- **FR-9** If a PDF download fails after retries, the metadata row is kept with `pdf_status='failed'`. At the start of each later run, papers in `pending`/`failed` status are retried first (up to `PDF_MAX_ATTEMPTS` total, default 5; after that they stay `failed` and are no longer retried, with a WARNING).
- **FR-10** Failure of one paper (metadata or PDF) is logged and skipped; it never aborts the run.
- **FR-11** Overlapping runs are prevented (in-process `max_instances=1`, plus a Postgres advisory lock so a second process cannot run concurrently).
- **FR-12** A CLI entry point `run-once` executes a single run immediately (for the operator and for tests). It uses the same code path as the scheduler. Scheduling is by APScheduler in the application process; no Airflow or external orchestrator.
- **FR-13** Every arXiv request attempt (API and PDF, including retries) emits one INFO log line `arxiv_request` with a UTC timestamp of when the request was sent, a monotonic start time, `gap_since_previous_request_ms`, endpoint kind, attempt number, status and elapsed time. A gap below the configured interval is logged as ERROR (it indicates a limiter bug). This makes the "no two calls closer than 3 s" criterion auditable from logs.
- **FR-14** Recency window: only papers submitted within the last `FETCH_WINDOW_DAYS` days (default 7) are candidates. The window is sent to arXiv as a `submittedDate:[start TO end]` range (GMT, `YYYYMMDDHHMM`) and also enforced client-side on `published_at`. Papers older than the window are never fetched, even if fewer than 5 new papers are found. PDF retries (FR-9) are not subject to the window.

### Non-functional
- **NFR-1** Schedule correctness is independent of server timezone; verified by test with the process TZ set to a different zone.
- **NFR-2** All arXiv calls comply with the `outbound-http` policy: explicit timeouts, classified retries, exponential backoff with jitter, max 3 attempts, total-wait cap, `Retry-After` honored.
- **NFR-3** All traffic to arXiv (API and PDF) goes through one `ArxivClient` with one shared limiter: no more than one request per 3 seconds, one connection at a time (arXiv Terms of Use). Retries count against the limit. Settings may raise the interval but validation rejects values below 3.0.
- **NFR-4** Idempotent: running the job twice never duplicates rows or re-downloads stored PDFs.
- **NFR-5** No secrets in repo or logs; config is a single typed settings object that fails fast.
- **NFR-6** A normal run should finish in under ~2 minutes (about 1 to 3 API calls and 5 PDFs at 3 s spacing). This is an expectation, not a hard SLA.
- **NFR-7** Timestamps stored in UTC (`timestamptz`).

## 3. Design

### Components
| Component | Responsibility |
|---|---|
| `settings.py` (`Settings`, pydantic-settings) | Only place reading env vars; validates; masks secrets. |
| `scheduler.py` | `AsyncIOScheduler` with `CronTrigger(hour=8, minute=0, timezone=ZoneInfo(SCHEDULE_TZ))`; calls `FetchJob.run`. Owns startup/shutdown. |
| `ArxivClient` | Sole HTTP user. `search_cs_ai(start, max_results)` returns parsed entries; `download_pdf(url, dest_tmp)` streams to a temp file. Owns base URL, timeouts, retries, limiter, User-Agent. |
| `RateLimiter` | Min-interval limiter (`asyncio.Lock` + monotonic clock, injectable clock/sleep). Shared by API and PDF calls. |
| `feed_parser.py` | Parses Atom into `PaperMeta` dataclasses; also detects arXiv's error-entry feed. |
| `PaperRepository` | All SQL: `existing_ids(ids)` (one batched query), `upsert_paper`, `mark_pdf_*`, `list_pdf_retry`, `list_expired`. |
| `PdfStore` | Path layout, atomic write (temp then rename), `%PDF-` magic check, SHA-256, delete. |
| `FetchJob` | Orchestrates a run (flow below) and returns a `RunSummary`. |
| `RetentionJob` | Selects expired PDFs, deletes files, updates rows. |

### Main flow (one run)
1. Acquire advisory lock; if not obtained, log and exit success (another run is active).
2. Retry set: load papers with `pdf_status in (pending, failed)` and attempts < max, oldest first, up to the cap. Download their PDFs.
3. Remaining budget = cap minus retry-set size. While budget > 0 and pages < `ARXIV_MAX_PAGES`: fetch a page (`start`, `max_results=ARXIV_PAGE_SIZE`); batch-query which IDs exist; take unseen entries in feed order up to budget.
4. For each new paper: upsert metadata row with `pdf_status='pending'` (short transaction, committed) then download PDF (no transaction open) then update row to `downloaded` (or `failed`, incrementing attempts).
5. Run `RetentionJob`.
6. Log `RunSummary` (counts: retried, new, downloaded, failed, expired, pages, duration). Release lock. Exit success unless a run-level failure occurred (see Error handling).

### How each intent constraint is met
- **08:00 IST regardless of server TZ:** the trigger carries an explicit `ZoneInfo("Asia/Kolkata")`; the `tzdata` package is a dependency so this also works on Windows hosts, which lack a system IANA database.
- **PDFs kept 1 month, metadata stays:** `RetentionJob` only touches files and PDF columns; there is no code path that deletes from `papers`.
- **Rate-limited, retried arXiv traffic:** see External calls.
- **Fewer than 5 is fine:** the loop ends normally on exhaustion; no assertion on count.

## 4. External calls (outbound-http)

| Item | arXiv API | arXiv PDF |
|---|---|---|
| Endpoint | `GET https://export.arxiv.org/api/query?search_query=cat:cs.AI+AND+submittedDate:[<start>+TO+<end>]&sortBy=submittedDate&sortOrder=descending&start=N&max_results=M` | `GET` the PDF link taken from each feed entry (`<link title="pdf">`, on `arxiv.org`) |
| Documented limit | One request per 3 seconds, single connection at a time, across all machines you control (arXiv API Terms of Use) | No separate documented limit; arXiv states "indiscriminate automated downloads … are not permitted". Treated under the same 3 s / single-connection limiter (conservative; see C-5) |
| Client limiter | `ARXIV_MIN_INTERVAL_SECONDS` default 3.0, minimum 3.0; `httpx.Limits(max_connections=1)` | same limiter instance |
| Timeouts | connect 5 s, read 30 s, write 30 s, pool 5 s | connect 5 s, read 60 s per chunk (`PDF_READ_TIMEOUT_SECONDS`), plus overall cap `PDF_TOTAL_TIMEOUT_SECONDS` default 300 |
| Retryable | `httpx.TimeoutException`, `httpx.TransportError`, 429 (honor `Retry-After`), 500/502/503/504 | same |
| Not retried | other 4xx (e.g. 400 bad query, 404) fail fast and log | 404 and other 4xx fail fast |
| Backoff | base 1 s, factor 2, random jitter, max 3 attempts, total wait cap `ARXIV_MAX_TOTAL_WAIT_SECONDS` default 60; wait is at least `Retry-After` | same |
| Exhausted | API: the run ends with run-level error (nothing new to process), logged ERROR, non-zero exit for `run-once`; scheduler keeps going. PDF: that paper is marked `failed`, run continues | as left |
| User-Agent | `ai-native-rag-arxiv-fetcher/<version> (+<ARXIV_CONTACT>)` | same |

Rules applied: single client class, no direct httpx use elsewhere, limiter acquired once per attempt (retries count), final failures logged with service, endpoint, status, attempts, elapsed time; no secrets exist in these requests.

## 5. Data model (persistence)

Migration `0001_create_papers` (Alembic). No `create_all()`. Only upgrades; downgrade drops the table (dev only, requires explicit approval to run anywhere else).

**Table `papers`**

| Column | Type | Notes |
|---|---|---|
| `id` | `bigint` identity | PK |
| `arxiv_id` | `text` NOT NULL | versionless, e.g. `2501.01234` or `cs/0501001`; **UNIQUE** |
| `version` | `int` NOT NULL | version seen when fetched |
| `title` | `text` NOT NULL | whitespace normalized |
| `abstract` | `text` NOT NULL | |
| `authors` | `jsonb` NOT NULL | ordered list of names |
| `primary_category` | `text` NOT NULL | |
| `categories` | `text[]` NOT NULL | |
| `published_at` | `timestamptz` NOT NULL | v1 submission date |
| `source_updated_at` | `timestamptz` NOT NULL | feed `<updated>` |
| `doi`, `journal_ref`, `comment` | `text` NULL | |
| `abs_url`, `pdf_url` | `text` NOT NULL | |
| `pdf_status` | `text` NOT NULL, CHECK in (`pending`,`downloaded`,`failed`,`expired`) | |
| `pdf_attempts` | `int` NOT NULL default 0 | |
| `pdf_path` | `text` NULL | relative to `PDF_DIR`; NULL when not on disk |
| `pdf_size_bytes` | `bigint` NULL | kept after expiry for audit |
| `pdf_sha256` | `text` NULL | kept after expiry |
| `pdf_downloaded_at` | `timestamptz` NULL | retention clock |
| `pdf_expired_at` | `timestamptz` NULL | |
| `created_at`, `updated_at` | `timestamptz` NOT NULL default `now()` | UTC; `updated_at` set on every write |

**Indexes** (each with its query)
- `UNIQUE (arxiv_id)`: dedupe lookup `WHERE arxiv_id = ANY(:ids)` and upsert conflict target.
- Partial `(created_at) WHERE pdf_status IN ('pending','failed')`: "PDFs to retry" query at start of run.
- Partial `(pdf_downloaded_at) WHERE pdf_status = 'downloaded'`: retention query.

No other indexes (nothing else queries this table in this intent).

**Write rules:** upsert via `INSERT ... ON CONFLICT (arxiv_id) DO UPDATE` (updates metadata fields but never regresses `pdf_status` from `downloaded`/`expired`, and never resets `pdf_downloaded_at`); parameterized SQLAlchemy only; one short transaction per paper step, none spanning HTTP; batched existence check (no N+1); all SQL in `PaperRepository`.

**Retention:** PDF files are deleted `PDF_RETENTION_DAYS` after `pdf_downloaded_at`. Metadata rows are never deleted by this system. File deletion is not a DB destructive change, and the intent (accepted) approves it; recorded here as that approval (see C-8).

**Files:** `PDF_DIR/<yyyy>/<arxiv_id with "/" replaced by "_">v<version>.pdf`; the DB stores the relative path, size, SHA-256.

## 6. Configuration (secrets-and-config)

Loaded once by `Settings`; `.env.example` is committed with all keys and dummy values; `.env` is gitignored.

| Name | Type | Default | Secret | Purpose |
|---|---|---|---|---|
| `DB_URL` | `SecretStr` | none (required) | **yes** | Postgres connection string (async driver, e.g. `postgresql+asyncpg://…`) |
| `ARXIV_CONTACT` | str | none (required) | no | Contact email/URL placed in User-Agent |
| `ARXIV_BASE_URL` | str | `https://export.arxiv.org/api/query` | no | API endpoint |
| `ARXIV_MIN_INTERVAL_SECONDS` | float (≥3.0) | 3.0 | no | Min spacing between any two arXiv requests |
| `ARXIV_CONNECT_TIMEOUT_SECONDS` | float | 5.0 | no | |
| `ARXIV_READ_TIMEOUT_SECONDS` | float | 30.0 | no | API read timeout |
| `PDF_READ_TIMEOUT_SECONDS` | float | 60.0 | no | PDF per-chunk read timeout |
| `PDF_TOTAL_TIMEOUT_SECONDS` | float | 300.0 | no | Overall cap per PDF |
| `ARXIV_RETRY_MAX_ATTEMPTS` | int | 3 | no | |
| `ARXIV_RETRY_BASE_SECONDS` | float | 1.0 | no | |
| `ARXIV_MAX_TOTAL_WAIT_SECONDS` | float | 60.0 | no | Backoff wait cap |
| `ARXIV_PAGE_SIZE` | int | 25 | no | `max_results` per query |
| `ARXIV_MAX_PAGES` | int | 4 | no | Paging safety cap |
| `FETCH_WINDOW_DAYS` | int (≥1) | 7 | no | Recency window: only papers submitted within this many days are fetched |
| `FETCH_MAX_PAPERS` | int | 5 | no | Per-run cap |
| `PDF_MAX_ATTEMPTS` | int | 5 | no | Lifetime download attempts per paper |
| `PDF_DIR` | path | `./data/pdfs` | no | PDF storage root |
| `PDF_RETENTION_DAYS` | int | 30 | no | Retention window |
| `SCHEDULE_TZ` | str | `Asia/Kolkata` | no | Schedule timezone |
| `SCHEDULE_HOUR` / `SCHEDULE_MINUTE` | int | 8 / 0 | no | Time of day |
| `SCHEDULE_MISFIRE_GRACE_SECONDS` | int | 3600 | no | Run late if process was briefly down at 08:00 (see T-21) |
| `LOG_LEVEL` | str | `INFO` | no | |

The only secret is `DB_URL`; it has no default and is never logged (log only host/db name derived safely, never the full string). Recommended enforcement (advisory skill): Claude permission deny on `Read(.env*)` and gitleaks in pre-commit and CI.

## 7. Error handling and logging

| Situation | Behavior |
|---|---|
| Missing/invalid setting | Process refuses to start (pydantic validation error, secrets masked). |
| API query fails after retries | ERROR with service/endpoint/status/attempts/elapsed; run ends; `run-once` exits non-zero; scheduler stays alive and tries next day. |
| arXiv returns HTTP 200 with an Atom error entry | Detected by the parser, treated as non-retryable failure of that query (ERROR). |
| Malformed entry in feed | WARNING, entry skipped, others processed. |
| PDF download fails after retries | WARNING, row `failed`, `pdf_attempts += 1`, continue (FR-9, FR-10). |
| Downloaded body not a PDF (no `%PDF-` header, e.g. HTML error page) | Treated as failure; temp file removed. |
| DB error on a paper | ERROR with arXiv ID, roll back that unit, continue; DB unavailable at start aborts run with ERROR. |
| File deletion fails (permissions) | WARNING, row left `downloaded`, retried next run. |
| File already missing at retention | INFO, row still marked `expired`. |
| Advisory lock held | INFO, exit success. |

Request timing: every arXiv attempt logs an `arxiv_request` line with send timestamp and gap since the previous request (FR-13); a gap under the configured interval is logged at ERROR.

Logging: stdlib `logging`, one line per event with structured key=value fields (run_id, arxiv_id, endpoint, status, attempt, elapsed_ms). One INFO `RunSummary` per run. Never log DB URL, full settings, or response bodies beyond status.

## 8. Test strategy

Rules: unit tests mock HTTP with `respx` (never real arXiv); fake clock for limiter and backoff (no real sleeps); DB tests use Postgres via `testcontainers`; tests set explicit settings and never read `.env`.

| ID | Test | Covers |
|---|---|---|
| T-1 | Integration: mock feed with 7 unseen cs.AI entries and PDFs; run once; assert exactly 5 rows (the 5 newest), each `downloaded`, file exists with matching size/SHA-256 | S1 |
| T-2 | Idempotency: run the job twice in a row with the same mock feed; row count unchanged, PDFs not re-downloaded; plus repository upsert twice | S4, C3, NFR-4 |
| T-3 | Mock feed has 0 unseen entries (all stored); run completes with success status, no errors | Proposed outcome (fewer than 5) |
| T-4 | Mock feed has 3 unseen entries; run stores 3, success, no extra paging past the budget | Proposed outcome (fewer than 5) |
| T-5 | Seed rows: one downloaded 31 days ago, one 29 days ago (fixed clock); retention deletes the old file only, row marked `expired` | S5 |
| T-6 | After T-5, assert both rows still exist with metadata intact; assert nothing deletes from `papers`; missing file tolerated | S5 |
| T-7 | Schedule: trigger's next fire time is 08:00 Asia/Kolkata (= 02:30 UTC) when process TZ is set to e.g. `America/New_York` and `UTC` | constraint 08:00 IST, FR-1 |
| T-8 | PDF failure then recovery: first run PDF 503 ×3 gives `failed` row; next run retries and gets `downloaded`; retry counts toward cap | FR-9, FR-3 |
| T-9 | Paging: first page all stored, second page has new entries; stops at cap / `ARXIV_MAX_PAGES` | FR-2, FR-4 |
| T-20 | Recency window: request carries the correct GMT `submittedDate` range for a fixed clock (also when server TZ is not UTC); an entry older than the window returned by a mock is ignored client-side; with only older papers available the run stores nothing and succeeds | FR-14 |
| T-10 | Parser, run against the real fixture(s) from plan step 0 (`tests/fixtures/`): categories, dates, versioned ID stripped, PDF link, authors; plus an error-entry feed fixture (hand-built only if a real one cannot be obtained, and labelled as synthetic) | FR-5 |
| T-11 | outbound-http: 503 then 200 succeeds; 404 not retried; `Retry-After` honored; retries exhausted raises; limiter spacing ≥3 s using fake clock, including retries; two concurrent callers serialized | NFR-2, NFR-3 |
| T-12 | Non-PDF response body rejected | Error handling |
| T-13 | Migration `0001` upgrades an empty Postgres cleanly; constraints (unique, check) enforced | persistence |
| T-14 | Settings: missing `DB_URL` or `ARXIV_CONTACT` fails; interval <3.0 fails; `repr(settings)` hides `DB_URL` | secrets-and-config |
| T-15 | Advisory lock: second concurrent run exits without work | FR-11 |
| T-16 | Simulated outage (respx): API returns 503 twice then 200, and a PDF times out once then succeeds; run completes with all 5 papers stored. Second case: outage longer than the retry budget, so the API query fails, run exits with error, nothing corrupt is stored, and a following run (outage over) recovers and stores the papers | S2, C2 |
| T-17 | Timing log: run a full multi-request job with a fake clock and capture logs; assert every `arxiv_request` record has `gap_since_previous_request_ms` ≥ 3000, including retried attempts and the API-to-PDF transition; a deliberately broken limiter makes the check fail | S3, C1, FR-13 |
| T-18 | One paper's metadata is malformed and another's PDF 404s; the other papers in the run are still stored and the run exits successfully | C4, FR-10 |
| T-19 | 429 with `Retry-After` and 400/404 behave per classification table (retry vs fail fast) | C2 |
| T-21 | Missed run: the process is down at 08:00 and starts within the misfire grace window; the job runs exactly once (not zero, not twice), and one that starts after the window does not run until the next day. Uses a fake clock/scheduler time, no real waiting | FR-1, FR-11, misfire decision |

## 9. Decisions

| Choice | Reason |
|---|---|
| `httpx.AsyncClient` | Mandated by outbound-http; supports streaming and fine timeouts. |
| `tenacity` | Mandated retry library; supports `Retry-After`-aware custom wait. |
| Custom min-interval limiter | Policy-specified; trivial, testable with injected clock. |
| Atom parsing with `feedparser` | Mature handling of Atom and `arxiv:` extension fields; avoids hand-rolled XML. (Behavior on `arxiv:` tags checked against the real fixture in plan step 0 (section 11).) |
| Postgres 16 with SQLAlchemy 2.x + Alembic + `asyncpg` | Persistence skill defaults. |
| APScheduler 3.11.x `AsyncIOScheduler` + `CronTrigger(timezone=…)` | Meets the intent's in-process, non-Airflow constraint; 3.x is stable (4.x is still alpha on PyPI), and trigger takes explicit timezone. |
| `tzdata` dependency | Windows has no system IANA tz database for `zoneinfo`. |
| Retention from `pdf_downloaded_at`, 30 days | Chosen by Rahul; deterministic and unaffected by a paper's age. |
| Keep row on PDF failure, retry next run | Chosen by Rahul; no paper lost, bounded by `PDF_MAX_ATTEMPTS`. |
| Query `cat:cs.AI` + `submittedDate` range, sorted by `submittedDate` desc | Chosen by Rahul (cross-lists included, recency window added); "most recent" = newest submissions within `FETCH_WINDOW_DAYS`. Range syntax verified in the arXiv API manual. |
| Postgres advisory lock | Cheap guard against concurrent runs from multiple processes. |
| HTTPS for the API | Docs show `http://`; HTTPS is preferred; confirmed or rejected by plan step 0. |
| Store versionless `arxiv_id` as natural key | Prevents a v2 of a stored paper being treated as new. |
| Temp file then atomic rename | No partial PDFs on disk after crash. |
| `testcontainers`, `respx`, `pytest-asyncio` | Per skills. |
| "Most recent" = `submittedDate` descending, i.e. original submission date (was C-2, accepted) | Matches arXiv's sort option; recently revised old papers are not "recent". |
| One shared 3 s / single-connection limiter for API and PDF traffic (was C-5, accepted) | arXiv documents the limit only for the API; applying it to PDFs is the conservative reading of "all traffic". |
| In-process scheduler with a misfire grace period (default 1 h) and no further catch-up of missed days (was C-7, accepted) | Late runs cover brief downtime; each run fetches the newest unseen papers, so gaps within the recency window self-heal. |
| Deleting PDF files after retention is approved by the accepted intent; no DB data is deleted (was C-8, accepted) | Records the persistence-rule-3 approval; the file deletion is not a database change. |
| Timing is measured between request send times, retries included (was C-14, accepted) | Stricter reading of arXiv's "one request every three seconds"; serialized requests enforce the single connection. |
| Recency window `FETCH_WINDOW_DAYS` (default 7), enforced via `submittedDate` range and client-side (was C-3) | Stops paging from pulling arbitrarily old papers; after an outage longer than the window, older unseen papers are skipped for good. Default of 7 days confirmed by Rahul. Window edges are in GMT per the arXiv manual. |
| Retries exhausted: mark PDF `failed`, or end the run if the API query fails; alert only via logs/exit code (was C-4, accepted) | No alert channel exists in 001. |
| The 5-paper cap includes PDF-retry papers (was C-10, accepted) | Bounded by `PDF_MAX_ATTEMPTS`; persistent failures can crowd out new papers for a few days. |
| Stored papers are not refreshed when a new version appears (was C-11, accepted for 001) | Keeps 001 simple; revisit in a later intent. |
| Always-on Windows host assumed; no containerization or service definition (was C-12, confirmed) | Out of 001's scope. |
| "Run recovers" = outage shorter than the retry budget recovers in-run; a longer outage fails cleanly and recovers at the next run (was C-13, accepted for now) | Max 3 attempts and 60 s wait cap; longer same-day recovery would change the intent's retry limit. |

## 10. Flagged concerns

None. All concerns raised during spec review are resolved and recorded under Decisions (section 9), Verify during implementation (section 11) or Carried forward (section 12).

## 11. Verify during implementation

Unknowns that cannot be decided away; they are checked with evidence during implementation (was C-9).

- **First plan step (step 0): record one real arXiv API response as a test fixture.** It settles: HTTPS at `export.arxiv.org`, the feed format and `arxiv:` extension tags, the PDF link form and host, and `feedparser` behavior on that real data.
- **Not settled by step 0; confirm early in implementation:**
  - `tenacity`, SQLAlchemy 2.x/asyncpg upsert and `testcontainers` details.
  - APScheduler `misfire_grace_time`/`coalesce` semantics (only the `CronTrigger` timezone parameter was confirmed from docs); T-21 tests the behavior.
  - Whether arXiv sends `Retry-After`, and whether it prefers `export.arxiv.org` for programmatic PDF fetches.
  - Whether arXiv's page-size guidance matters for `ARXIV_PAGE_SIZE`.
- **Already verified from official docs:** ToU limit (1 req/3 s, single connection), `cat:cs.AI`, `submittedDate` range syntax, `sortBy`, paging params, feed field list, errors as Atom entry, APScheduler 3.11.3 stable (4.x alpha), `CronTrigger(timezone=...)`, `httpx.Timeout` usage.

### Step 0 detail: verification spike

Before any production code, make real, minimal calls to arXiv and keep the evidence:

1. **One API call** (single request, polite): `GET https://export.arxiv.org/api/query?search_query=cat:cs.AI+AND+submittedDate:[<start>+TO+<end>]&sortBy=submittedDate&sortOrder=descending&start=0&max_results=5`, with the real User-Agent (`ai-native-rag-arxiv-fetcher/<version> (+<contact>)`). Save the raw response body to `tests/fixtures/arxiv_cs_ai_page.xml`.
2. **One PDF request** (at least 3 s after step 1) to the PDF link found in that fixture. Record only status, final host after redirects, `Content-Type`, `Content-Length` and the first 5 bytes (`%PDF-`) in a short notes file next to the fixture. Do **not** commit the PDF.
3. **Optionally**, one more call with a deliberately invalid query to capture a real error-entry feed as `tests/fixtures/arxiv_error.xml` (also single, spaced 3 s). If it does not produce an error feed, keep T-10's synthetic error fixture, labelled synthetic.
4. **Record findings** (HTTPS works or not, redirects, link form, any `Retry-After`/rate headers seen) in section 11 of this spec or the plan, and correct this spec where reality differs.

Rules for the spike: no more than these 2 to 3 requests, spaced at least 3 s apart, sequential; save only the response body and the notes above, never request headers; the fixture is arXiv metadata, which arXiv's terms of use for the API let you retrieve and store for research use (their metadata licensing was not checked here; check before publishing the repo publicly). Tests then read the fixture files; unit tests still never call arXiv.

Needs from Rahul: the real contact address for the User-Agent (`ARXIV_CONTACT`). I will not substitute your account email without your say-so.

Because the fixture is date-windowed real data, the parser and ingest tests read it as static data and do not depend on today's date.

## 12. Carried forward to later intents

- **arXiv terms of use on PDFs (was C-6).** arXiv permits retrieving and storing e-prints for personal or research use, but not storing and serving them from your own servers without permission or a permissive license. Therefore, for intent 002 and later:
  - Answers link to arXiv (the paper's abstract/PDF page on arxiv.org).
  - PDFs stored by this fetcher are never served to users.
- Source: arXiv API Terms of Use (info.arxiv.org/help/api/tou.html). This is a design constraint, not legal advice.

## 13. Out of scope (from the intent)

PDF parsing (Docling), chunking, embeddings, OpenSearch indexing, search/answer API, other categories, other paper sources.
