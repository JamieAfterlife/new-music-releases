"""Run the tracker from a Hermes no-agent cron job."""

import os
from pathlib import Path
import subprocess
import sys

# Running this file inside the project needs no configuration. If it is copied
# into Hermes' scripts directory, set NEW_MUSIC_PROJECT_DIR to the project path.
PROJECT_DIR = Path(os.environ.get("NEW_MUSIC_PROJECT_DIR", Path(__file__).resolve().parent))
PYTHON = os.environ.get("NEW_MUSIC_PYTHON", sys.executable)

result = subprocess.run(
    [str(PYTHON), "music_release_tracker.py", "check", "--quiet-if-none"],
    cwd=PROJECT_DIR,
    text=True,
    encoding="utf-8",
    errors="replace",
    capture_output=True,
)
if result.returncode:
    print(result.stderr.strip() or result.stdout.strip() or "New music check failed")
    raise SystemExit(result.returncode)
if result.stdout.strip():
    print(result.stdout.strip())
