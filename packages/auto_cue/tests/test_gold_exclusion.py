"""Few-shot retrieval must not return the track itself or a same-title copy."""

from auto_cue.gold import GoldPool, PoolTrack, bpm_or_duration_close, identity_keys


def _track(path: str, bpm: float, title: str, beats: int = 400, dur: float = 200.0) -> PoolTrack:
    return PoolTrack(
        path=path,
        small_file=None,
        bpm=bpm,
        first_beat_s=0.0,
        total_beats=beats,
        duration_s=dur,
        cues={},
        title=title,
    )


def test_identity_ignores_remix_tag_and_short_titles():
    keys = identity_keys("Kanye West", "Power (Nikademis Flip)", "DJ Music/Power.mp3")
    assert "t:power" in keys
    assert "a:kanye west|power" in keys
    assert identity_keys("", "Mix", "ab.mp3") == set()


def test_bpm_or_duration_close():
    assert bpm_or_duration_close(128, 200, 130, 100)
    assert bpm_or_duration_close(100, 200, 140, 210)
    assert not bpm_or_duration_close(100, 200, 140, 260)


def test_nearest_and_exclude_drop_self_and_same_title():
    original = _track("lib/Power.mp3", 128, "Power (Original Mix)")
    copy = _track("lib/Power-copy.mp3", 128.5, "Power (Club Remix)", beats=402)
    other = _track("lib/Other Song.mp3", 128, "Other Song Here")
    pool = GoldPool(
        tracks={t.path: t for t in (original, copy, other)},
        audio_map={},
    )

    nearest = pool.get_nearest_by_bpm(
        128, 400, max_results=5, require_audio=False, exclude_paths={original.path}
    )
    assert original not in nearest

    excluded = pool.paths_to_exclude(
        self_path=original.path,
        title=original.title,
        bpm=original.bpm,
        duration_s=original.duration_s,
        extra_paths={"lib/held-out.mp3"},
    )
    assert original.path in excluded
    assert copy.path in excluded
    assert other.path not in excluded
    assert "lib/held-out.mp3" in excluded

    nearest = pool.get_nearest_by_bpm(
        original.bpm,
        original.total_beats,
        max_results=5,
        require_audio=False,
        exclude_paths=excluded,
    )
    assert nearest == [other]
