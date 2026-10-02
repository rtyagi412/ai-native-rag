#!/usr/bin/env python3
"""PostToolUse: format and lint the edited Python file only (fast, scoped).
Exit 2 shows remaining lint errors to Claude so it fixes them immediately."""
import json
import os
import shutil
import subprocess
import sys

PROJECT = os.environ.get("CLAUDE_PROJECT_DIR", ".")
path = json.load(sys.stdin).get("tool_input", {}).get("file_path", "")

if not path.endswith(".py") or shutil.which("uv") is None:
    sys.exit(0)


def ruff(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["uv", "run", "--quiet", "ruff", *args, path],
                          cwd=PROJECT, capture_output=True, text=True)


fmt = ruff("format")
if fmt.returncode != 0 and ("Failed to spawn" in fmt.stderr or "not found" in fmt.stderr):
    sys.exit(0)  # ruff not installed yet (before the skeleton step): skip silently

check = ruff("check", "--fix")
if check.returncode != 0:
    print(f"ruff found issues in {path} that need fixing:\n{check.stdout}{check.stderr}",
          file=sys.stderr)
    sys.exit(2)
sys.exit(0)
