"""Prompt file loading with configurable lookup order."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

PromptType = Literal["clean", "crystal", "composite"]

# Full Album Prompt files (clean/crystal) must be Will's real prompts, not stubs.
# Composite is a separate locked short prompt and must not use this threshold.
MIN_ALBUM_PROMPT_CHARS = 2000
ALBUM_TRANSFORM_TYPES: frozenset[str] = frozenset({"clean", "crystal"})
AQUA_HEX = "#33C2E0"

PROMPT_ENV_VARS: dict[PromptType, str] = {
    "clean": "HUNTINGSZN_PROMPT_CLEAN",
    "crystal": "HUNTINGSZN_PROMPT_CRYSTAL",
    "composite": "HUNTINGSZN_PROMPT_COMPOSITE",
}

PROMPT_FILENAMES: dict[PromptType, list[str]] = {
    "clean": ["album-prompt-clean.txt", "Album Prompt - clean.txt"],
    "crystal": ["album-prompt-crystal.txt", "Album Prompt - crystal.txt"],
    "composite": ["album-prompt-composite.txt", "Album Prompt - composite.txt"],
}


def _package_prompts_dir() -> Path:
    """Return the prompts directory bundled with the package."""
    return Path(__file__).parent / "prompts"


def _asset_dirs() -> list[Path]:
    """Repo/drive locations that hold the real Album Prompt files."""
    return [
        Path.cwd() / "huntingszn-assets" / "cover-prompts",
        Path("/Volumes/HuntingSzn/Thumbnails"),
    ]


def _lookup_paths(prompt_type: PromptType) -> list[Path]:
    """Return ordered list of paths to search for the prompt file.

    Package-bundled prompts are last so a stale stub can never beat drive/repo
    assets. Env-var overrides are handled separately in ``load_prompt``.
    """
    filenames = PROMPT_FILENAMES[prompt_type]
    paths: list[Path] = []

    for directory in _asset_dirs():
        for fname in filenames:
            paths.append(directory / fname)

    pkg_dir = _package_prompts_dir()
    for fname in filenames:
        paths.append(pkg_dir / fname)

    return paths


def load_prompt(prompt_type: PromptType) -> str:
    """Load prompt text from the first available source.

    Lookup order:
    1. Environment variable (HUNTINGSZN_PROMPT_CLEAN, HUNTINGSZN_PROMPT_CRYSTAL,
       or HUNTINGSZN_PROMPT_COMPOSITE)
    2. ./huntingszn-assets/cover-prompts/ (relative to cwd)
    3. /Volumes/HuntingSzn/Thumbnails/ (Album Prompt - clean/crystal.txt)
    4. Package prompts/ directory (fallback only)

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


def validate_prompt_content(prompt: str, prompt_type: str | None = None) -> None:
    """Validate prompt text.

    Always rejects ``HUNTINGSZN FLIP`` and requires ``HUNTINGSZN EDIT``, except
    for ``composite`` which is a locked short images.edit instruction.

    For clean/crystal only:
    - length must be greater than 2000 characters (rejects package stubs)
    - must contain ``#33C2E0``
    - clean must contain ``Re-Colour``
    - crystal must contain ``Facet`` or ``facet``

    Raises:
        ValueError: If the prompt is a stub or missing required markers.
    """
    if prompt_type == "composite":
        return

    prompt_upper = prompt.upper()
    if "HUNTINGSZN FLIP" in prompt_upper:
        raise ValueError(
            "Prompt contains 'HUNTINGSZN FLIP' but should contain 'HUNTINGSZN EDIT'. "
            "Please update the prompt file."
        )
    if "HUNTINGSZN EDIT" not in prompt_upper:
        raise ValueError(
            "Prompt must contain the 'HUNTINGSZN EDIT' wordmark. Please update the prompt file."
        )

    if prompt_type not in ALBUM_TRANSFORM_TYPES:
        return

    if len(prompt) <= MIN_ALBUM_PROMPT_CHARS:
        raise ValueError(
            f"{prompt_type} prompt is a stub ({len(prompt)} chars; need "
            f">{MIN_ALBUM_PROMPT_CHARS}). Package prompts/ files must not silently "
            "replace Will's full Album Prompt text. Stubs can contain "
            "'HUNTINGSZN EDIT' and still produce the wrong transform."
        )
    if AQUA_HEX not in prompt:
        raise ValueError(
            f"{prompt_type} prompt is missing required aqua hex {AQUA_HEX}. "
            "This looks like a stub or the wrong Album Prompt file."
        )
    if prompt_type == "clean" and "Re-Colour" not in prompt:
        raise ValueError(
            "clean prompt must contain 'Re-Colour' (HuntingSzn Re-Colour v6.0). "
            "A stub or the crystal prompt was loaded instead of the real clean Album Prompt."
        )
    if prompt_type == "crystal" and "Facet" not in prompt and "facet" not in prompt:
        raise ValueError(
            "crystal prompt must contain 'Facet' or 'facet'. "
            "A stub or the clean prompt was loaded instead of the real crystal Album Prompt."
        )


def get_prompt(prompt_type: PromptType, *, validate: bool = True) -> str:
    """Load and optionally validate a prompt.

    Args:
        prompt_type: "clean", "crystal", or "composite".
        validate: If True, validate transform prompts don't contain FLIP
            wordmark and (for clean/crystal) are not stubs. Composite prompts
            skip those rules; they are a locked images.edit instruction
            without HUNTINGSZN EDIT.

    Returns:
        The prompt text content.
    """
    prompt = load_prompt(prompt_type)
    if validate:
        validate_prompt_content(prompt, prompt_type)
    return prompt
