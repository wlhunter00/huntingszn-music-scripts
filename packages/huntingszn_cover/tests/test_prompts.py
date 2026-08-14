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
