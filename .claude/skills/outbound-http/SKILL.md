---
name: outbound-http
description: Resilience and etiquette rules for every call a backend makes to an external service (third-party APIs, LLM or embedding providers, file downloads, webhooks, crawlers). Use whenever writing, changing, reviewing, or specifying code that calls an external HTTP API or downloads files, including HTTP clients, API wrappers, SDK calls and fetchers, even if the user never mentions retries, timeouts or rate limits. Applies to any stack (Python/FastAPI, Java/Spring Boot).
---

# Outbound HTTP policy

Any system you don't own can be slow, can fail, and can throttle you. Code must assume all three.

## Rules

1. **Explicit timeouts on every call.** Set connect and read timeouts; never rely on library defaults (often infinite). Default: connect 5s, read 30s. Large downloads may use a longer read timeout, stated in the spec.
2. **One client class per external service** (e.g. `ArxivClient`). It owns base URL, timeouts, retries, rate limiting and User-Agent. Business code never calls the HTTP library directly.
3. **Classify failures before retrying.**

   | Failure | Retry? |
   |---|---|
   | Timeout, connection error | Yes |
   | 429 Too Many Requests | Yes, honoring `Retry-After` |
   | 500, 502, 503, 504 | Yes |
   | Any other 4xx | No. Fail fast and log |
   | Non-idempotent POST | Only if the API supports idempotency keys |

4. **Exponential backoff with jitter.** Base 1s, factor 2, random jitter, max 3 attempts, cap on total wait. If `Retry-After` is present, wait at least that long.
5. **Client-side rate limiting** at the provider's documented limit, enforced inside the client so every caller shares one limiter. Retries count against the limit. If no limit is documented, choose a conservative one and record it in the spec.
6. **Identify the client** with a User-Agent containing the app name and a contact URL or email.
7. **Log final failures** with service, endpoint, status, attempt count and elapsed time. Never log tokens, auth headers or request bodies containing secrets.
8. **Isolate failures in batch work.** A failing item is logged and skipped; it does not abort the batch unless the spec says otherwise.
9. **Configurable, not hard-coded.** Timeouts, retry counts and rate limits come from settings.

## In a spec or plan

Include an **External calls** section listing, per service: endpoints used, documented rate limit, timeout values, retryable failures, and behavior once retries are exhausted.

## Tests required

- Unit tests never hit the real service; mock at the HTTP layer.
- Cover: retry on 503 then success; no retry on 404; `Retry-After` honored; retries exhausted surfaces an error; rate-limit spacing verified with an injected fake clock, never real sleeps.

## Stack specifics

**Python:** `httpx.AsyncClient` with `httpx.Timeout(30.0, connect=5.0)`, created once and closed on shutdown (FastAPI lifespan). Retries via `tenacity` (`retry_if_exception`, `wait_random_exponential`, `stop_after_attempt`). Rate limit via a small min-interval limiter (`asyncio.Lock` + `time.monotonic`) with an injectable clock. Mock with `respx`. Do not use `requests` in async code.

**Java:** Spring `RestClient` (or `WebClient` if reactive) with connect/read timeouts on the request factory. Retries via Resilience4j `Retry` with `IntervalFunction.ofExponentialRandomBackoff` and a retry-on predicate; rate limit via Resilience4j `RateLimiter`. Mock with WireMock (use scenarios for 503 → 200).
