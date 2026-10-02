---
name: secrets-and-config
description: Rules for configuration, secrets and credentials in backend services. Use whenever adding a setting, environment variable, API key, password, token or connection string; creating or editing a settings/config class; writing logging or error handling that could expose values; editing Dockerfiles, compose files or CI config; or describing configuration in a spec or plan. Applies to any stack (Python/FastAPI, Java/Spring Boot).
---

# Secrets and configuration policy

Config changes between environments; code doesn't. Secrets never enter the repository, the logs, or the agent's context.

## Rules

1. **Config comes from the environment** (12-factor), loaded once into a single typed settings object at startup.
2. **Fail fast.** The app refuses to start if a required setting is missing or invalid.
3. **Read env vars only in the settings module.** No `os.environ` / `System.getenv` scattered through the code.
4. **No secrets anywhere in the repo:** code, tests, fixtures, docs, comments, commit messages, Dockerfiles, compose files. Use placeholders.
5. **`.env` is local-only and gitignored.** Commit `.env.example` with every key and dummy values, updated in the same change that adds a setting.
6. **Secrets are masked types** so they never print in reprs, logs or errors.
7. **Secrets have no defaults.** Non-secret settings (timeouts, schedules) may have safe defaults.
8. **Never log** secrets, auth headers, full connection strings, or a dump of the settings object.
9. **Consistent naming:** upper snake case, prefixed by subsystem (e.g. `ARXIV_MIN_INTERVAL_SECONDS`, `DB_URL`).
10. **Accidental commit = leaked.** If a secret reaches git history, flag it for rotation; deleting the commit is not enough.

## In a spec or plan

Include a **Configuration** section: a table of settings with name, type, default, whether it is a secret, and purpose.

## Tests required

- Settings validation fails when a required value is missing.
- Tests set explicit test values; they never read a developer's real `.env`.

## Enforcement note

This skill is advisory. Back it with deterministic controls: a Claude Code permission deny on `Read(.env*)`, and a secret scanner (e.g. gitleaks) in pre-commit and CI.

## Stack specifics

**Python:** `pydantic-settings` `BaseSettings` with `SecretStr` for secrets; `env_file=".env"` for local development only.

**Java:** `@ConfigurationProperties` records with `@Validated`; secrets injected from environment or a secret manager; never commit `application-prod.yml` containing secrets.
