"""Verify the selectors gate fires when selectors are unset."""

import pytest

from mashup_pop_finder import getsongbpm, selectors, songkeyfinder


def test_require_raises_on_none() -> None:
    with pytest.raises(RuntimeError, match="not configured"):
        selectors.require("SOMETHING", None)


def test_require_raises_on_empty_string() -> None:
    with pytest.raises(RuntimeError, match="not configured"):
        selectors.require("SOMETHING", "")


def test_require_passes_value_through() -> None:
    assert selectors.require("X", "ok") == "ok"


def test_songkeyfinder_resolve_base_song_refuses_without_selectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(selectors, "SONGKEYFINDER_BASE_URL", None)
    with pytest.raises(RuntimeError, match="not configured"):
        songkeyfinder.resolve_base_song("Levitating", "Dua Lipa")


def test_songkeyfinder_list_songs_in_key_refuses_without_selectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(selectors, "SONGKEYFINDER_BASE_URL", None)
    with pytest.raises(RuntimeError, match="not configured"):
        songkeyfinder.list_songs_in_key("B minor", limit=10)


def test_getsongbpm_lookup_refuses_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GETSONGBPM_API_KEY", raising=False)
    with pytest.raises(getsongbpm.GetSongBpmError, match="GETSONGBPM_API_KEY"):
        getsongbpm.lookup("Levitating", "Dua Lipa")
