#!/usr/bin/env python3
"""Download audio for Spotify tracks via official metadata + external sources.

Spotify is used for catalog metadata only (Web API). Audio is resolved from
YouTube (default) or SoundCloud — never by decrypting Spotify streams.
See docs/research/viwizard-spotify-converter-analysis.md.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from config.paths import DJ_SPOTIFY
from downloads._common import dated_output_dir, run_yt_dlp
from downloads.metadata import (
    DownloadManifest,
    HistoryEntry,
    apply_spotify_tags,
    artist_title_filename,
    sanitize_filename,
)
from downloads.source_resolver import resolve_source
from downloads.spotify_api import TrackMeta, expand_inputs, parse_spotify_ref


def _find_new_file(out_dir: Path, before: set[Path]) -> Path | None:
    after = {p for p in out_dir.iterdir() if p.is_file()}
    created = sorted(after - before, key=lambda p: p.stat().st_mtime, reverse=True)
    audio_ext = {".mp3", ".m4a", ".opus", ".ogg", ".flac", ".wav", ".webm"}
    for path in created:
        if path.suffix.lower() in audio_ext:
            return path
    return created[0] if created else None


def _rename_to_spotify(path: Path, track: TrackMeta, *, audio_mode: str) -> Path:
    ext = path.suffix.lstrip(".") or ("mp3" if audio_mode == "mp3" else path.suffix.lstrip("."))
    target_name = artist_title_filename(track, ext=ext)
    target = path.with_name(target_name)
    if target == path:
        return path
    if target.exists():
        # Avoid clobber: keep unique suffix
        stem = sanitize_filename(f"{track.artists_joined} - {track.name}")
        target = path.with_name(f"{stem} ({track.id[:8]}).{ext}")
    return path.rename(target)


def process_track(
    track: TrackMeta,
    out_dir: Path,
    manifest: DownloadManifest,
    *,
    source: str,
    min_score: float,
    audio_mode: str,
    dry_run: bool,
    skip_existing: bool,
    no_tag: bool,
    auth_token: str | None,
) -> bool:
    print(f"→ {track.artists_joined} — {track.name} [{track.id}]")

    if skip_existing and manifest.is_done(track.id):
        print("  skip: already in manifest")
        return True

    # Also skip if target filename already exists
    presumed = out_dir / artist_title_filename(
        track, ext="mp3" if audio_mode == "mp3" else "m4a"
    )
    if skip_existing and presumed.exists():
        manifest.record(
            HistoryEntry(
                spotify_id=track.id,
                title=track.name,
                artists=track.artists_joined,
                status="ok",
                output_path=str(presumed),
                error="skipped existing file",
            )
        )
        print(f"  skip: exists {presumed.name}")
        return True

    result = resolve_source(track, source=source, min_score=min_score)  # type: ignore[arg-type]
    if result.candidate is None:
        err = result.error or "no candidate"
        print(f"  fail: {err}", file=sys.stderr)
        if result.rejected:
            best = result.rejected[0]
            print(
                f"  best rejected: [{best.score:.1f}] {best.title} ({best.url})",
                file=sys.stderr,
            )
        manifest.record(
            HistoryEntry(
                spotify_id=track.id,
                title=track.name,
                artists=track.artists_joined,
                status="unmatched",
                error=err,
            )
        )
        return False

    cand = result.candidate
    print(
        f"  match [{cand.score:.1f}] {cand.source}: {cand.title} — {cand.url}"
    )
    print(f"  reason: {cand.reason}")

    if dry_run:
        manifest.record(
            HistoryEntry(
                spotify_id=track.id,
                title=track.name,
                artists=track.artists_joined,
                status="dry-run",
                source=cand.source,
                source_url=cand.url,
                confidence=cand.score,
            )
        )
        return True

    before = {p for p in out_dir.iterdir() if p.is_file()}
    # Force a predictable basename via yt-dlp template, then retag
    base = sanitize_filename(f"{track.artists_joined} - {track.name}")
    template = str(out_dir / f"{base}.%(ext)s")
    ok = run_yt_dlp(
        cand.url,
        out_dir,
        auth_token=auth_token if cand.source == "soundcloud" else None,
        audio_mode=audio_mode,
        no_playlist=True,
        output_template=template,
    )
    if not ok:
        manifest.record(
            HistoryEntry(
                spotify_id=track.id,
                title=track.name,
                artists=track.artists_joined,
                status="download_failed",
                source=cand.source,
                source_url=cand.url,
                confidence=cand.score,
                error="yt-dlp failed",
            )
        )
        print("  fail: yt-dlp", file=sys.stderr)
        return False

    downloaded = out_dir / f"{base}.mp3"
    if not downloaded.exists():
        found = _find_new_file(out_dir, before)
        if found is None:
            manifest.record(
                HistoryEntry(
                    spotify_id=track.id,
                    title=track.name,
                    artists=track.artists_joined,
                    status="download_failed",
                    source=cand.source,
                    source_url=cand.url,
                    confidence=cand.score,
                    error="output file not found",
                )
            )
            print("  fail: output missing", file=sys.stderr)
            return False
        downloaded = _rename_to_spotify(found, track, audio_mode=audio_mode)
    else:
        downloaded = _rename_to_spotify(downloaded, track, audio_mode=audio_mode)

    if not no_tag:
        try:
            apply_spotify_tags(downloaded, track)
        except Exception as exc:  # noqa: BLE001
            print(f"  warn: tagging failed: {exc}", file=sys.stderr)

    manifest.record(
        HistoryEntry(
            spotify_id=track.id,
            title=track.name,
            artists=track.artists_joined,
            status="ok",
            source=cand.source,
            source_url=cand.url,
            confidence=cand.score,
            output_path=str(downloaded),
        )
    )
    print(f"  saved: {downloaded}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve Spotify track/album/playlist metadata via the official API, "
            "then download matching audio from YouTube (default) or SoundCloud. "
            "Does not decrypt Spotify streams."
        )
    )
    parser.add_argument(
        "urls",
        nargs="+",
        help="Spotify track/album/playlist URL, URI, or track id",
    )
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument(
        "--to-library",
        action="store_true",
        help=f"Write into DJ Spotify library ({DJ_SPOTIFY})",
    )
    parser.add_argument(
        "--best",
        action="store_true",
        help="Keep native best audio instead of MP3 320k",
    )
    parser.add_argument(
        "--source",
        choices=("auto", "youtube", "soundcloud"),
        default="auto",
        help="External audio source (default: auto = YouTube then SoundCloud)",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=55.0,
        help="Minimum match confidence 0-100 (default: 55)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Max tracks to process")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip tracks already ok in manifest or present as target filename",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve metadata + source only; do not download",
    )
    parser.add_argument(
        "--no-tag",
        action="store_true",
        help="Do not overwrite tags/artwork with Spotify metadata",
    )
    parser.add_argument(
        "--market",
        default=os.environ.get("SPOTIFY_MARKET"),
        help="Spotify market code (e.g. US)",
    )
    parser.add_argument(
        "--auth-token",
        default=os.environ.get("SOUNDCLOUD_AUTH_TOKEN"),
        help="SoundCloud OAuth token for Go+ (also SOUNDCLOUD_AUTH_TOKEN)",
    )
    args = parser.parse_args()

    # Validate refs early for clearer errors
    for raw in args.urls:
        try:
            parse_spotify_ref(raw)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(2)

    if args.to_library:
        out = Path(args.output_dir) if args.output_dir else DJ_SPOTIFY
        out.mkdir(parents=True, exist_ok=True)
    else:
        out = dated_output_dir(Path(args.output_dir) if args.output_dir else None)

    try:
        tracks = expand_inputs(args.urls, market=args.market, limit=args.limit)
    except Exception as exc:  # noqa: BLE001
        print(f"error: Spotify API: {exc}", file=sys.stderr)
        sys.exit(1)

    if not tracks:
        print("error: no tracks resolved", file=sys.stderr)
        sys.exit(1)

    print(f"Queued {len(tracks)} track(s) → {out}")
    manifest = DownloadManifest(out / "sp-dl-history.json")
    audio_mode = "best" if args.best else "mp3"

    failures = 0
    for track in tracks:
        ok = process_track(
            track,
            out,
            manifest,
            source=args.source,
            min_score=args.min_score,
            audio_mode=audio_mode,
            dry_run=args.dry_run,
            skip_existing=args.skip_existing,
            no_tag=args.no_tag,
            auth_token=args.auth_token,
        )
        if not ok:
            failures += 1

    print(f"Done. ok={len(tracks) - failures} failed={failures} dir={out}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
