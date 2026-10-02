# Review instructions

## Passes
Run three passes and tag each finding with its pass:
- **Bugs**: logic errors, broken edge cases, race conditions, unhandled failures, subtle regressions.
- **Security**: injection, secrets or PII in code/logs/errors, unsafe file paths, unvalidated input.
- **Compliance**: the change matches specs/ and plans/, and follows every relevant skill in .claude/skills/.

## What Important means here
Important = would break behavior, lose or duplicate data, leak a secret, violate an
external service's terms (e.g. rate limits), breach a skill policy, or weaken a test.
Everything about style, naming and structure is a Nit.

## Cap the nits
Report at most five nits; summarize the rest as a count.

## Do not report
Formatting and lint issues (ruff and mypy enforce them), generated files, and anything
under intent/ or specs/ (human-owned artifacts).
