from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


class PromptLoadError(ValueError):
    """Raised when a prompt file is missing or structurally invalid."""


# Spec section 8 requires prompts to be loaded from markdown at runtime and for the
# filename plus version to be recorded in run metadata. Canonical names are listed
# here so a rename in prompts/ fails loudly instead of silently falling back.
PROMPT_FILES: Dict[str, str] = {
    "system": "system_prompt.md",
    "resume_builder": "resume_builder.md",
    "cover_letter": "cover_letter.md",
    "interview": "interview.md",
    "job_matcher": "job_search_prompt.md",
    "validator": "validator.md",
    "application_answers": "application_prompt.md",
    "notification": "notification_message.md",
}

_VERSION_PATTERNS = (
    re.compile(r"^\s*version\s*:\s*(?P<version>[^\s]+)\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^#+\s*version\s*\n+\s*(?P<version>[^\s\n]+)", re.IGNORECASE | re.MULTILINE),
)


@dataclass(frozen=True)
class LoadedPrompt:
    key: str
    path: Path
    text: str
    version: str

    @property
    def filename(self) -> str:
        return self.path.name

    def as_metadata(self) -> Dict[str, str]:
        """Shape recorded in metadata.json / Application.json prompt_versions."""
        return {"file": self.filename, "version": self.version}


def load_prompt(repo_root: Path, key: str) -> LoadedPrompt:
    if key not in PROMPT_FILES:
        raise PromptLoadError(f"Unknown prompt key '{key}'. Known keys: {', '.join(sorted(PROMPT_FILES))}")

    prompt_path = (repo_root / "prompts" / PROMPT_FILES[key]).resolve()
    if not prompt_path.exists():
        raise PromptLoadError(f"Missing prompt file: {prompt_path}")

    text = prompt_path.read_text(encoding="utf-8").strip()
    if not text:
        raise PromptLoadError(f"Prompt file is empty: {prompt_path}")

    return LoadedPrompt(key=key, path=prompt_path, text=text, version=_extract_version(text))


def _extract_version(text: str) -> str:
    for pattern in _VERSION_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group("version").strip()
    return "unversioned"


def collect_prompt_versions(*prompts: LoadedPrompt) -> Dict[str, Any]:
    """Build the prompt_versions object required by the Application JSON contract."""
    return {prompt.key: prompt.as_metadata() for prompt in prompts}
