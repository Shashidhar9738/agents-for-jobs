from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.agent_core.config_loader import validate_all_configs


def main() -> int:
    repo_root = REPO_ROOT
    ok, errors = validate_all_configs(repo_root)
    if ok:
        print("[OK] All configurations are valid for all candidates.")
        return 0

    print("[ERROR] Configuration validation failed:")
    for idx, error in enumerate(errors, start=1):
        print(f"  {idx}. {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
