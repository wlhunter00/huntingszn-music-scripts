"""Tests for prompt loading and validation."""

import os
from pathlib import Path

import pytest

from huntingszn_cover.prompts import (
    MIN_ALBUM_PROMPT_CHARS,
    _package_prompts_dir,
    get_prompt,
    load_prompt,
    validate_prompt_content,
)

PACKAGE_PROMPT_FILES = (
    "album-prompt-clean.txt",
    "album-prompt-crystal.txt",
)


def _package_prompt_text(name: str) -> str:
    return (_package_prompts_dir() / name).read_text(encoding="utf-8")


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

    def test_rejects_stub_clean_even_with_wordmark(self) -> None:
        stub = "Short HUNTINGSZN EDIT stub with #33C2E0 and Re-Colour"
        with pytest.raises(ValueError, match=r"stub.*2000"):
            validate_prompt_content(stub, prompt_type="clean")

    def test_rejects_stub_crystal_even_with_wordmark(self) -> None:
        stub = "Short HUNTINGSZN EDIT stub with #33C2E0 and Facet"
        with pytest.raises(ValueError, match=r"stub.*2000"):
            validate_prompt_content(stub, prompt_type="crystal")

    def test_clean_requires_aqua_hex(self) -> None:
        prompt = ("HUNTINGSZN EDIT Re-Colour " + "x" * MIN_ALBUM_PROMPT_CHARS)
        with pytest.raises(ValueError, match=r"#33C2E0"):
            validate_prompt_content(prompt, prompt_type="clean")

    def test_clean_requires_recolour(self) -> None:
        prompt = ("HUNTINGSZN EDIT #33C2E0 " + "x" * MIN_ALBUM_PROMPT_CHARS)
        with pytest.raises(ValueError, match="Re-Colour"):
            validate_prompt_content(prompt, prompt_type="clean")

    def test_crystal_requires_facet(self) -> None:
        prompt = ("HUNTINGSZN EDIT #33C2E0 " + "x" * MIN_ALBUM_PROMPT_CHARS)
        with pytest.raises(ValueError, match="[Ff]acet"):
            validate_prompt_content(prompt, prompt_type="crystal")

    def test_composite_skips_length_and_wordmark_rules(self) -> None:
        """Composite is a locked short prompt; do not apply the >2000 rule."""
        locked = (
            "The first image is the main album cover. Combine the second image "
            "into it as secondary. One cohesive cover, both recognizable. "
            "Do not split the canvas."
        )
        validate_prompt_content(locked, prompt_type="composite")


class TestPackagePromptsAreFullSize:
    """Fail if packaged clean/crystal files regress to stubs."""

    @pytest.mark.parametrize("name", PACKAGE_PROMPT_FILES)
    def test_package_prompt_is_not_stub_sized(self, name: str) -> None:
        text = _package_prompt_text(name)
        assert len(text) > MIN_ALBUM_PROMPT_CHARS, (
            f"{name} is stub-sized ({len(text)} chars); "
            "package prompts must be Will's full Album Prompt files"
        )
        assert "#33C2E0" in text
        assert "HUNTINGSZN EDIT" in text

    def test_package_clean_has_recolour_marker(self) -> None:
        text = _package_prompt_text("album-prompt-clean.txt")
        assert "Re-Colour" in text

    def test_package_crystal_has_facet_marker(self) -> None:
        text = _package_prompt_text("album-prompt-crystal.txt")
        assert "Facet" in text or "facet" in text


class TestLoadPrompt:
    """Tests for prompt file loading."""

    def test_load_from_package_prompts(self) -> None:
        """Should load prompts bundled with the package."""
        prompt = load_prompt("clean")
        assert "HUNTINGSZN EDIT" in prompt
        assert "#33C2E0" in prompt
        assert "Re-Colour" in prompt
        assert len(prompt) > MIN_ALBUM_PROMPT_CHARS

    def test_load_crystal_prompt(self) -> None:
        """Should load crystal prompt from package."""
        prompt = load_prompt("crystal")
        assert "HUNTINGSZN EDIT" in prompt
        assert "#33C2E0" in prompt
        assert "facet" in prompt.lower()
        assert len(prompt) > MIN_ALBUM_PROMPT_CHARS

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

    def test_load_order_prefers_env_over_longer_assets(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assets = tmp_path / "huntingszn-assets" / "cover-prompts"
        assets.mkdir(parents=True)
        (assets / "album-prompt-clean.txt").write_text(
            "ASSET FILE " + "a" * MIN_ALBUM_PROMPT_CHARS + " HUNTINGSZN EDIT"
        )
        env_file = tmp_path / "env-clean.txt"
        env_file.write_text("ENV OVERRIDE HUNTINGSZN EDIT")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("HUNTINGSZN_PROMPT_CLEAN", str(env_file))
        assert load_prompt("clean") == "ENV OVERRIDE HUNTINGSZN EDIT"

    def test_load_order_prefers_assets_over_package(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A longer cwd asset file must win over the packaged prompt."""
        assets = tmp_path / "huntingszn-assets" / "cover-prompts"
        assets.mkdir(parents=True)
        longer = (
            "FROM-ASSETS " + "b" * MIN_ALBUM_PROMPT_CHARS + " HUNTINGSZN EDIT #33C2E0 Re-Colour"
        )
        (assets / "album-prompt-clean.txt").write_text(longer)
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("HUNTINGSZN_PROMPT_CLEAN", raising=False)
        prompt = load_prompt("clean")
        assert prompt == longer.strip()
        assert "FROM-ASSETS" in prompt

    def test_falls_back_to_package_when_no_assets(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("HUNTINGSZN_PROMPT_CLEAN", raising=False)
        prompt = load_prompt("clean")
        assert len(prompt) > MIN_ALBUM_PROMPT_CHARS
        assert "Re-Colour" in prompt
        assert "#33C2E0" in prompt

    def test_lookup_uses_cwd_not_hardcoded_workspace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from huntingszn_cover.prompts import _lookup_paths

        monkeypatch.chdir(tmp_path)
        paths = [p.resolve() for p in _lookup_paths("clean")]
        hardcoded = Path("/workspace/huntingszn-assets/cover-prompts/album-prompt-clean.txt")
        cwd_fallback = tmp_path / "huntingszn-assets" / "cover-prompts" / "album-prompt-clean.txt"
        pkg = _package_prompts_dir() / "album-prompt-clean.txt"
        assert cwd_fallback.resolve() in paths
        assert pkg.resolve() in paths
        assert paths.index(cwd_fallback.resolve()) < paths.index(pkg.resolve())
        if tmp_path.resolve() != Path("/workspace").resolve():
            assert hardcoded not in paths


class TestGetPrompt:
    """Tests for get_prompt with validation."""

    def test_get_clean_validates(self) -> None:
        """get_prompt should validate by default."""
        prompt = get_prompt("clean")
        assert "HUNTINGSZN EDIT" in prompt
        assert "#33C2E0" in prompt
        assert "Re-Colour" in prompt
        assert len(prompt) > MIN_ALBUM_PROMPT_CHARS

    def test_get_crystal_validates(self) -> None:
        """get_prompt should validate crystal prompt."""
        prompt = get_prompt("crystal")
        assert "HUNTINGSZN EDIT" in prompt
        assert "#33C2E0" in prompt
        assert "facet" in prompt.lower()
        assert len(prompt) > MIN_ALBUM_PROMPT_CHARS

    def test_get_prompt_rejects_stub_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub = tmp_path / "stub-clean.txt"
        stub.write_text("HUNTINGSZN EDIT #33C2E0 Re-Colour stub")
        monkeypatch.setenv("HUNTINGSZN_PROMPT_CLEAN", str(stub))
        with pytest.raises(ValueError, match=r"stub.*2000"):
            get_prompt("clean")

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
