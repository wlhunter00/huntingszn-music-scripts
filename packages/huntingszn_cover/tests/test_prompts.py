"""Tests for prompt loading and validation."""

import os
from pathlib import Path

import pytest

from huntingszn_cover.prompts import (
    get_prompt,
    load_prompt,
    validate_prompt_content,
)


class TestValidatePromptContent:
    """Tests for prompt content validation."""

    def test_valid_edit_wordmark(self) -> None:
        """Prompt with HUNTINGSZN EDIT should pass validation."""
        prompt = "This is a HUNTINGSZN EDIT - transform the image."
        validate_prompt_content(prompt)

    def test_invalid_flip_wordmark_raises(self) -> None:
        """Prompt with HUNTINGSZN FLIP should raise ValueError."""
        prompt = "This is a HUNTINGSZN FLIP - transform the image."
        with pytest.raises(ValueError, match=r"FLIP.*should contain.*EDIT"):
            validate_prompt_content(prompt)

    def test_case_insensitive_flip_detection(self) -> None:
        """FLIP detection should be case-insensitive."""
        prompt = "This is a huntingszn flip version."
        with pytest.raises(ValueError, match="FLIP"):
            validate_prompt_content(prompt)

    def test_no_wordmark_raises(self) -> None:
        """Prompt without HUNTINGSZN EDIT wordmark should fail validation."""
        prompt = "Transform this image with a teal aesthetic."
        with pytest.raises(ValueError, match="HUNTINGSZN EDIT"):
            validate_prompt_content(prompt)


class TestLoadPrompt:
    """Tests for prompt file loading."""

    def test_load_from_package_prompts(self) -> None:
        """Should load prompts bundled with the package."""
        prompt = load_prompt("clean")
        assert "HUNTINGSZN EDIT" in prompt
        assert len(prompt) > 50

    def test_load_crystal_prompt(self) -> None:
        """Should load crystal prompt from package."""
        prompt = load_prompt("crystal")
        assert "HUNTINGSZN EDIT" in prompt
        assert "teal" in prompt.lower() or "crystal" in prompt.lower()

    def test_load_composite_prompt(self) -> None:
        """Should load the locked mashup composite prompt from package."""
        prompt = load_prompt("composite")
        assert prompt == (
            "The first image is the main album cover. Combine the second image into it as secondary. "
            "One cohesive cover, both recognizable. Do not split the canvas."
        )
        assert "blend" not in prompt.lower()
        assert "mashup_name" not in prompt

    def test_env_var_override(self, tmp_path: Path) -> None:
        """Environment variable should override package prompts."""
        custom_prompt = "Custom prompt for testing - HUNTINGSZN EDIT"
        prompt_file = tmp_path / "custom-clean.txt"
        prompt_file.write_text(custom_prompt)

        os.environ["HUNTINGSZN_PROMPT_CLEAN"] = str(prompt_file)
        try:
            prompt = load_prompt("clean")
            assert prompt == custom_prompt
        finally:
            del os.environ["HUNTINGSZN_PROMPT_CLEAN"]

    def test_lookup_uses_cwd_not_hardcoded_workspace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from huntingszn_cover.prompts import _lookup_paths

        monkeypatch.chdir(tmp_path)
        paths = [p.resolve() for p in _lookup_paths("clean")]
        hardcoded = Path("/workspace/huntingszn-assets/cover-prompts/album-prompt-clean.txt")
        cwd_fallback = tmp_path / "huntingszn-assets" / "cover-prompts" / "album-prompt-clean.txt"
        assert cwd_fallback.resolve() in paths
        if tmp_path.resolve() != Path("/workspace").resolve():
            assert hardcoded not in paths


class TestGetPrompt:
    """Tests for get_prompt with validation."""

    def test_get_clean_validates(self) -> None:
        """get_prompt should validate by default."""
        prompt = get_prompt("clean")
        assert "HUNTINGSZN EDIT" in prompt

    def test_get_crystal_validates(self) -> None:
        """get_prompt should validate crystal prompt."""
        prompt = get_prompt("crystal")
        assert "HUNTINGSZN EDIT" in prompt

    def test_get_prompt_composite_returns_locked_text(self) -> None:
        """get_prompt('composite') returns the locked text and skips wordmark validation."""
        prompt = get_prompt("composite")
        assert prompt == (
            "The first image is the main album cover. Combine the second image into it as secondary. "
            "One cohesive cover, both recognizable. Do not split the canvas."
        )
        assert "HUNTINGSZN EDIT" not in prompt
        assert "blend" not in prompt.lower()

    def test_packaged_composite_prompt_file_is_locked_text(self) -> None:
        from huntingszn_cover.prompts import _package_prompts_dir

        text = (_package_prompts_dir() / "album-prompt-composite.txt").read_text(
            encoding="utf-8"
        ).strip()
        assert text == get_prompt("composite")

    def test_assets_composite_prompt_copy_matches_locked_text(self) -> None:
        assets = (
            Path(__file__).resolve().parents[3]
            / "huntingszn-assets"
            / "cover-prompts"
            / "album-prompt-composite.txt"
        )
        assert assets.is_file()
        assert assets.read_text(encoding="utf-8").strip() == get_prompt("composite")

    def test_validation_can_be_disabled(self, tmp_path: Path) -> None:
        """Should be able to skip validation."""
        bad_prompt = "This is a HUNTINGSZN FLIP - bad wordmark"
        prompt_file = tmp_path / "bad-clean.txt"
        prompt_file.write_text(bad_prompt)

        os.environ["HUNTINGSZN_PROMPT_CLEAN"] = str(prompt_file)
        try:
            prompt = get_prompt("clean", validate=False)
            assert prompt == bad_prompt
        finally:
            del os.environ["HUNTINGSZN_PROMPT_CLEAN"]
