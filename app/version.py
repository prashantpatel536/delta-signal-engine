"""Build and version metadata for deployment diagnostics."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

SIGNAL_ENGINE_VERSION = "2.1.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUILD_INFO_PATH = PROJECT_ROOT / "data" / "build_info.json"


def _run_git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            value = result.stdout.strip()
            return value or None
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def get_git_commit() -> str:
    env_commit = os.getenv("GIT_COMMIT", "").strip()
    if env_commit:
        return env_commit
    commit = _run_git("rev-parse", "HEAD")
    if commit:
        return commit
    if BUILD_INFO_PATH.exists():
        try:
            import json

            data = json.loads(BUILD_INFO_PATH.read_text(encoding="utf-8"))
            if data.get("git_commit"):
                return str(data["git_commit"])
        except (OSError, ValueError):
            pass
    return "unknown"


def get_build_timestamp() -> str:
    env_ts = os.getenv("BUILD_TIMESTAMP", "").strip()
    if env_ts:
        return env_ts
    git_ts = _run_git("log", "-1", "--format=%cI")
    if git_ts:
        return git_ts
    if BUILD_INFO_PATH.exists():
        try:
            import json

            data = json.loads(BUILD_INFO_PATH.read_text(encoding="utf-8"))
            if data.get("build_timestamp"):
                return str(data["build_timestamp"])
        except (OSError, ValueError):
            pass
    return datetime.now(timezone.utc).isoformat()
