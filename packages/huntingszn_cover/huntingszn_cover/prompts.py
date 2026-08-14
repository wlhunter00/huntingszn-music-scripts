"""Prompt file loading with configurable lookup order."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

PromptType = Literal["clean", "crystal"]

PROMPT_ENV_VARS: dict[PromptType, str] = {
    "clean": "HUNTINGSZN_PROMPT_CLEAN",
    "crystal": "HUNTINGSZN_PROMPT_CRYSTAL",
}

PROMPT_FILENAMES: dict[PromptType, list[str]] = {
    "clean": ["album-prompt-clean.txt", "Album Prompt - clean.txt"],
    "crystal": ["album-prompt-crystal.txt", "Album Prompt - crystal.txt"],
}


def _package_prompts_dir() -> Path:
    """Return the prompts directory bundled with the package."""
    return Path(__file__).parent / "prompts"


def _lookup_paths(prompt_type: PromptType) -> list[Path]:
    """Return ordered list of paths to search for the prompt file."""
    filenames = PROMPT_FILENAMES[prompt_type]
    paths: list[Path] = []

    pkg_dir = _package_prompts_dir()
    for fname in filenames:
        paths.append(pkg_dir / fname)

    workspace_dir = Path("/workspace/huntingszn-assets/cover-prompts")
    for fname in filenames:
        paths.append(workspace_dir / fname)

    volume_dir = Path("/Volumes/HuntingSzn/Thumbnails")
    for fname in filenames:
        paths.append(volume_dir / fname)

    return paths


def load_prompt(prompt_type: PromptType) -> str:
    """Load prompt text from the first available source.

    Lookup order:
    1. Environment variable (HUNTINGSZN_PROMPT_CLEAN or HUNTINGSZN_PROMPT_CRYSTAL)
    2. Package prompts/ directory
    3. /workspace/huntingszn-assets/cover-prompts/
    4. /Volumes/HuntingSzn/Thumbnails/

    Raises:
        FileNotFoundError: If no prompt file is found in any location.
    """
    env_var = PROMPT_ENV_VARS[prompt_type]
    env_value = os.environ.get(env_var)
    if env_value:
        env_path = Path(env_value)
        if env_path.is_file():
            return env_path.read_text(encoding="utf-8").strip()

    for path in _lookup_paths(prompt_type):
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()

    searched = [str(p) for p in _lookup_paths(prompt_type)]
    raise FileNotFoundError(
        f"No prompt file found for '{prompt_type}'. "
        f"Searched: {searched}. "
        f"Set {env_var} environment variable or place the file in one of the above locations."
    )


def validate_prompt_content(prompt: str) -> None:
    """Validate that prompt contains expected EDIT wordmark, not FLIP.

    Raises:
        ValueError: If prompt contains FLIP instead of EDIT wordmark.
    """
    prompt_upper = prompt.upper()
    if "HUNTINGSZN FLIP" in prompt_upper:
        raise ValueError(
            "Prompt contains 'HUNTINGSZN FLIP' but should contain 'HUNTINGSZN EDIT'. "
            "Please update the prompt file."
        )


def get_prompt(prompt_type: PromptType, *, validate: bool = True) -> str:
    """Load and optionally validate a prompt.

    Args:
        prompt_type: Either "clean" or "crystal".
        validate: If True, validate the prompt doesn't contain FLIP wordmark.

    Returns:
        The prompt text content.
    """
    prompt = load_prompt(prompt_type)
    if validate:
        validate_prompt_content(prompt)
    return prompt
