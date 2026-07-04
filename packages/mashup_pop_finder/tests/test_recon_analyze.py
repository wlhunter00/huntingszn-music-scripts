from pathlib import Path

from mashup_pop_finder.recon.analyze import analyze_html, render_summary, run

_LISTING_HTML = """\
<!doctype html>
<html><head><title>Songs in B minor — SongKeyFinder</title></head>
<body>
  <main>
    <h1>Songs in B minor</h1>
    <ul class="song-list">
      <li class="song-row"><a href="/song/levitating"><span class="title">Levitating</span><span class="artist">Dua Lipa</span></a><span class="key">B minor</span></li>
      <li class="song-row"><a href="/song/blinding-lights"><span class="title">Blinding Lights</span><span class="artist">The Weeknd</span></a><span class="key">B minor</span></li>
      <li class="song-row"><a href="/song/take-on-me"><span class="title">Take On Me</span><span class="artist">a-ha</span></a><span class="key">B minor</span></li>
      <li class="song-row"><a href="/song/four"><span class="title">Four</span><span class="artist">Demo</span></a><span class="key">B minor</span></li>
      <li class="song-row"><a href="/song/five"><span class="title">Five</span><span class="artist">Demo</span></a><span class="key">B minor</span></li>
    </ul>
  </main>
</body></html>
"""

_DETAIL_HTML = """\
<!doctype html>
<html><head><title>Levitating</title></head>
<body>
  <h1>Levitating — Dua Lipa</h1>
  <div class="meta">
    <span class="song-key">B minor</span>
    <span class="song-bpm">103 BPM</span>
  </div>
</body></html>
"""


class TestAnalyzeHtml:
    def test_picks_up_title(self) -> None:
        a = analyze_html(Path("listing.html"), _LISTING_HTML)
        assert a.title is not None
        assert "Songs in B minor" in a.title

    def test_finds_repeating_listing_rows(self) -> None:
        a = analyze_html(Path("listing.html"), _LISTING_HTML)
        block_selectors = {sel for sel, _ in a.repeating_blocks}
        assert any("song-row" in sel for sel in block_selectors), (
            f"expected song-row block; got {block_selectors}"
        )

    def test_finds_key_text(self) -> None:
        a = analyze_html(Path("detail.html"), _DETAIL_HTML)
        assert a.key_hits, "expected at least one key hit"
        assert any("B minor" in h.matched or "minor" in h.matched.lower() for h in a.key_hits)

    def test_finds_bpm_text(self) -> None:
        a = analyze_html(Path("detail.html"), _DETAIL_HTML)
        assert a.bpm_hits, "expected at least one BPM hit"
        # The matched substring should contain "103"
        assert any("103" in h.matched for h in a.bpm_hits)

    def test_best_guess_block_includes_key_and_bpm(self) -> None:
        a = analyze_html(Path("detail.html"), _DETAIL_HTML)
        block = a.best_guess_block()
        assert "SONG_PAGE_KEY_SELECTOR" in block
        assert "SONG_PAGE_BPM_SELECTOR" in block


class TestRender:
    def test_render_empty_handles_no_files(self) -> None:
        out = render_summary([])
        assert "No HTML files" in out

    def test_render_includes_filename(self) -> None:
        a = analyze_html(Path("listing.html"), _LISTING_HTML)
        out = render_summary([a])
        assert "listing.html" in out
        assert "Best-guess" in out or "Top tags" in out


class TestRun:
    def test_run_writes_summary_md(self, tmp_path: Path) -> None:
        (tmp_path / "a.html").write_text(_LISTING_HTML, encoding="utf-8")
        (tmp_path / "b.html").write_text(_DETAIL_HTML, encoding="utf-8")
        analyses, _summary = run(tmp_path)
        assert len(analyses) == 2
        summary_path = tmp_path / "SUMMARY.md"
        assert summary_path.exists()
        content = summary_path.read_text(encoding="utf-8")
        assert "a.html" in content and "b.html" in content

    def test_run_empty_dir(self, tmp_path: Path) -> None:
        analyses, summary = run(tmp_path)
        assert analyses == []
        assert "No HTML files" in summary
