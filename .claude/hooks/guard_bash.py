#!/usr/bin/env python3
"""PreToolUse guard for shell commands. Exit 2 blocks the command; stderr is shown to Claude."""
import json
import os
import re
import subprocess
import sys

PROJECT = os.environ.get("CLAUDE_PROJECT_DIR", ".")

RULES = [
    (r"\bgit\s+push\b.*(\s|:)(main|master)(\s|$)",
     "Never push to main/master. Push the feature branch and open a PR."),
    (r"\bgit\s+push\b.*(\s--force\b|\s-f\b|--force-with-lease)",
     "Force-push is not allowed."),
    (r"--no-verify\b",
     "Skipping git hooks (--no-verify) is not allowed."),
    (r"\bgh\s+pr\s+merge\b",
     "The agent never merges. A human reviews, tests and merges the PR."),
    (r"\bgit\s+(reset\s+--hard|clean\s+-\w*f)",
     "Destructive git commands are not allowed."),
    (r"\b(cat|less|more|head|tail|type|grep|sed|awk|source)\b[^|;&]*\.env(?!\.example)\b",
     "Reading .env is not allowed. The app loads its values at runtime."),
]


def current_branch() -> str:
    result = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                            cwd=PROJECT, capture_output=True, text=True)
    return result.stdout.strip()


cmd = json.load(sys.stdin).get("tool_input", {}).get("command", "")

for pattern, reason in RULES:
    if re.search(pattern, cmd):
        print(f"BLOCKED by guard_bash: {reason}", file=sys.stderr)
        sys.exit(2)

if re.search(r"\bgit\s+push\b", cmd) and current_branch() in ("main", "master"):
    print("BLOCKED by guard_bash: you are on main. Create a feature branch first.",
          file=sys.stderr)
    sys.exit(2)

sys.exit(0)
