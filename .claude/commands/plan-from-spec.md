---
description: Produce an implementation plan from an accepted spec (run in plan mode)
argument-hint: <path to spec, e.g. specs/001-arxiv-fetcher.md>
---

Read the spec at $ARGUMENTS, its intent (linked at the top of the spec), and
CLAUDE.md. Produce an implementation plan. Do not write any code.

The plan will be executed autonomously by an agent after I approve it, so it
must be complete enough that someone who never saw this conversation could
implement it from the plan alone.

The plan must contain:
1. Steps, in order. Each step is small enough for one commit and lists:
   files created/changed, requirements covered (FR/NFR IDs), the tests that
   prove it (T-IDs from the spec), and the command that verifies it.
   Every step ends with `make lint` and `make test` green.
2. Step 1 sets up the project skeleton so every command in CLAUDE.md works.
   Any "Verify during implementation" items in the spec come next, before
   production code.
3. Test-first: within each step, write the tests before the code.
4. Coverage: a table mapping every requirement and every test ID in the
   spec to a step. Nothing in the spec may be left unmapped.
5. Risks: what this change could break, the riskiest step and why, and
   alternatives you considered but rejected.
6. Stop conditions: when the implementing agent must stop and ask a human
   instead of continuing (e.g. the spec is contradicted by reality, a test
   cannot pass without changing the spec, a dependency not in the spec is
   needed, any destructive change).
7. Definition of done.

Ask me questions before finalizing. When I approve, write the plan to
plans/ with the same file name as the spec, and stop. Do not start
implementing.