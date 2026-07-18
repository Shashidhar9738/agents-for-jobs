from __future__ import annotations

import os
from pathlib import Path

from src.agent_core.net import use_system_trust_store

_ENV_LOADED = False


def load_env_file(repo_root: Path) -> bool:
    """Load .env into the process environment.

    Every entry point needs this: provider credentials live in .env, and without
    it the AI client silently reports "no credential" and the whole pipeline
    quietly degrades to deterministic output. Values already set in the real
    environment win, so an explicit export still overrides the file.
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return True

    env_path = repo_root / ".env"
    if not env_path.exists():
        return False

    try:
        from dotenv import load_dotenv
    except ImportError:
        _load_env_manually(env_path)
    else:
        load_dotenv(env_path, override=False)

    _ENV_LOADED = True
    return True


def _load_env_manually(env_path: Path) -> None:
    """Minimal KEY=VALUE parser so python-dotenv stays an optional dependency."""
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def init_runtime(repo_root: Path) -> None:
    """Prepare the process: credentials loaded, TLS routed through the OS store."""
    load_env_file(repo_root)
    use_system_trust_store()
