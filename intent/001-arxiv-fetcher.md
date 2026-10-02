# Intent 001: arXiv paper fetcher

Author: Rahul. Status: accepted.

## Problem
The RAG system needs a steady supply of recent AI papers. Fetching them by hand
doesn't scale, and an unthrottled fetcher risks being blocked by arXiv.

## Proposed outcome
A scheduled Python job runs daily at 08:00 IST and fetches up to 5 of the most
recent cs.AI papers not already stored. It saves their metadata in Postgres and
downloads their PDFs to disk. Fewer than 5 new papers is a normal outcome, not
an error. Failed calls are retried, and all traffic to arXiv is rate-limited.
PDFs older than 1 month are removed from disk.

## Affected users and systems
- Rahul (operator of the job; later, users of the RAG bot)
- arXiv API (metadata) and arxiv.org (PDF downloads)
- Postgres (paper metadata), local disk (PDFs)

## Constraints
- At most 1 request every 3 seconds to arXiv, covering API calls and PDF downloads.
- Transient failures (timeouts, 5xx, 429) are retried with exponential backoff
  and a retry limit; permanent failures (other 4xx) are not retried.
- Re-running the job must not create duplicate papers (idempotent).
- One failed paper must not fail the whole run; it is logged and skipped.
- Scheduling uses a Python in-process scheduler, not Airflow.
- The job runs at 08:00 IST (Asia/Kolkata), independent of the server's timezone.
- PDFs are kept on disk for 1 month, then deleted; paper metadata stays in Postgres.

## Out of scope
PDF parsing (Docling), chunking, embeddings, OpenSearch indexing,
search/answer API, other categories, other paper sources.

## Success looks like
- A daily run stores up to 5 new cs.AI papers in Postgres, each with its PDF on disk.
- A simulated arXiv outage triggers retries and the run recovers.
- Request timing logs show no two arXiv calls closer than 3 seconds.
- Running the job twice in a row adds no duplicates.
- PDFs older than 1 month are deleted; their metadata rows remain.


## Open questions
None.