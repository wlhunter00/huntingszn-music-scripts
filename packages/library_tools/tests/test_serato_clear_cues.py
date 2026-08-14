import dataclasses

from library_tools.serato_clear_cues import clear_cues_rule
from serato_tools.track_cues_v2 import TrackCuesV2


def test_clear_cues_rule_returns_none_when_empty():
    track = TrackCuesV2.TrackCuesInfo()
    assert clear_cues_rule(track) is None


def test_clear_cues_rule_clears_existing_cues():
    cue = TrackCuesV2.CueEntry(
        field1=b"\x00",
        index=0,
        position=1000,
        field4=b"\x00",
        color=TrackCuesV2.CueColors.RED.value,
        field6=b"\x00\x00",
        name="DROP",
    )
    track = TrackCuesV2.TrackCuesInfo(cues=[cue])
    result = clear_cues_rule(track)
    assert result is not None
    assert result.cues == []
    assert result is not track
    assert track.cues == [cue]


def test_clear_cues_rule_preserves_loops():
    loop = TrackCuesV2.LoopEntry(
        field1=b"\x00",
        index=0,
        startposition=0,
        endposition=4000,
        field5=b"\x00\x00\x00\x00",
        field6=b"\x00\x00\x00\x00",
        color=TrackCuesV2.CueColors.RED.value,
        locked=False,
        name="LOOP",
    )
    cue = TrackCuesV2.CueEntry(
        field1=b"\x00",
        index=1,
        position=2000,
        field4=b"\x00",
        color=TrackCuesV2.CueColors.BLUE1.value,
        field6=b"\x00\x00",
        name="HIT",
    )
    track = TrackCuesV2.TrackCuesInfo(cues=[cue], loops=[loop])
    result = clear_cues_rule(track)
    assert result is not None
    assert result.cues == []
    assert result.loops == [loop]
    assert dataclasses.replace(track, cues=[]) == result
