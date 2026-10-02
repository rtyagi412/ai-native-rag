#!/usr/bin/env python3
"""PreToolUse guard for file edits. Exit 2 blocks the edit; stderr is shown to Claude."""
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()
TESTS_LOCK = PROJECT / ".claude" / "state" / "tests-locked"


def block(reason: str) -> None:
    print(f"BLOCKED by guard_edits: {reason}", file=sys.stderr)
    sys.exit(2)


def is_committed(rel: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"HEAD:{rel}"],
        cwd=PROJECT, capture_output=True,
    )
    return result.returncode == 0


data = json.load(sys.stdin)
raw = data.get("tool_input", {}).get("file_path", "")
if not raw:
    sys.exit(0)

path = Path(raw).resolve()  # handles Windows backslashes and relative paths
try:
    rel = path.relative_to(PROJECT).as_posix()
except ValueError:
    sys.exit(0)  # outside the repo (e.g. Claude's own plan/scratch files): not our concern
name = path.name

if rel.startswith(("intent/", "specs/")):
    block("intent/ and specs/ are human-approved artifacts. Do not edit them during "
          "implementation. Stop and flag the disagreement to a human instead.")

if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
    block(".env files are local-only and must never be written by the agent.")

if rel.startswith("migrations/versions/") and is_committed(rel):
    block("Committed migrations are never edited (persistence skill). Create a new migration.")

if rel.startswith("tests/") and TESTS_LOCK.exists():
    block("Tests are locked for this plan step. Make the code pass the existing tests. "
          "If a test is genuinely wrong, stop and ask a human (plan stop condition).")

sys.exit(0)
