---
description: Implement an approved plan autonomously, then verify, review, push and open a PR
argument-hint: <path to plan, e.g. plans/001-arxiv-fetcher.md>
---

Implement the approved plan at $ARGUMENTS end to end. Work autonomously, but obey
every stop condition in the plan: when one triggers, stop and report to me instead
of improvising.

## 0. Preconditions (stop if any fails)
- The plan, its spec and its intent exist and are accepted; the working tree is clean.
- The plan's "Human prerequisites" are all satisfied. Check what you can by running
  commands; never read .env and never substitute placeholder values.
- Create branch `feat/<plan file name without .md>` from main.

## 1. For each plan step, in order
1. If the step lists T-IDs, delegate to the **test-writer** subagent. Review its
   report, then commit the tests: `test(step N): <summary>`.
2. Create the file `.claude/state/tests-locked` (tests are now read-only).
3. Implement the step exactly as the plan says. Loop: `make lint` and `make test`,
   fix the code, repeat until both are green. Budget: 5 fix attempts per step.
   If the budget runs out, stop and report.
4. If you had to depart from the plan, update the plan file in the same commit and
   state why.
5. Run `rm .claude/state/tests-locked`, then commit: `feat(step N): <summary>`.

## 2. Verify
Delegate to the **verifier** subagent. Fix any FAIL and re-verify.
Budget: 2 rounds; then stop and report.

## 3. Review
Delegate to the **code-reviewer** subagent. Fix every Important finding (tests stay
locked while fixing review findings, so lock them first), re-run `make lint` and
`make test`, then request a fresh review. Budget: 2 rounds. Nits: fix if trivial,
otherwise list them in the PR.

## 4. Push and open the PR
Push the branch and run `gh pr create --base main` with a body containing:
- Summary, and links to the intent, spec and plan files
- Steps completed, with commit hashes
- Final `make lint` and `make test` output
- Verifier report table
- Review findings and how each was resolved; remaining nits
- Deviations from the plan (or "none")
- **Manual test checklist** for the human, derived from the intent's
  "Success looks like" section, with the exact commands to run

## 5. Stop
Never merge. Report the PR URL and wait for the human.
