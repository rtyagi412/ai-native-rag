---
description: Generate a requirements and design spec from an accepted intent.md
argument-hint: <path to intent file, e.g. intent/002-core-rag.md>
---

Read the intent at $ARGUMENTS and produce a requirements and design spec for it.
Write it to specs/ using the same file name as the intent
(e.g. intent/002-core-rag.md → specs/002-core-rag.md).
Do not write any code or create any other files.

Apply every skill in .claude/skills/ that is relevant to this intent, and
include the sections those skills require (e.g. External calls, Data model,
Configuration). List which skills you applied at the top of the spec.

The spec must contain:
1. Traceability: link to the intent, and show which requirement covers
   each intent constraint and success criterion.
2. Requirements: numbered functional (FR-x) and non-functional (NFR-x).
3. Design: components and responsibilities, main flows, and how each
   intent constraint is met.
4. The sections required by the applied skills.
5. Error handling and logging.
6. Test strategy: map every "Success looks like" line in the intent to
   at least one test.
7. Decisions: every library or approach chosen, with a one-line reason.
8. Flagged concerns: uncertainties, ambiguities in the intent, and policy
   conflicts. Do not guess silently.
9. Out of scope (carried from the intent).

Before writing, ask me any questions needed to remove ambiguity.
Verify external API or library details against official documentation
rather than from memory, and flag anything you could not verify.