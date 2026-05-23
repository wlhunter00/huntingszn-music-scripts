from dataclasses import dataclass, field


@dataclass(frozen=True)
class Song:
    title: str
    artist: str


@dataclass(frozen=True)
class SongMeta:
    title: str
    artist: str
    key: str | None = None
    bpm: float | None = None
    source_url: str | None = None


@dataclass(frozen=True)
class Candidate:
    title: str
    artist: str
    detail_url: str | None = None


@dataclass(frozen=True)
class MatchResult:
    candidate: Candidate
    bpm: float
    ratio: float
    match_type: str  # "1x" | "2x" | "0.5x"
    key: str | None = None
    extras: dict[str, str] = field(default_factory=dict)
