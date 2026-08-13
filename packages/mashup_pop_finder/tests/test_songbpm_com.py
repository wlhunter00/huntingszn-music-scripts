import httpx
import respx

from mashup_pop_finder import songbpm_com

_WONDERWALL_HTML = """\
<!doctype html>
<html><body>
<h1>Wonderwall</h1>
175 BPM
<h3>Song Metrics</h3>
<p>Tempo (BPM) 175</p>
<p>Wonderwall is a song by Oasis with a tempo of 175 BPM.</p>
</body></html>
"""


@respx.mock
def test_lookup_parses_tempo_from_metrics() -> None:
    route = respx.get("https://songbpm.com/@oasis/wonderwall").mock(
        return_value=httpx.Response(200, text=_WONDERWALL_HTML)
    )
    meta = songbpm_com.lookup("Wonderwall", "Oasis")
    assert route.called
    assert meta is not None
    assert meta.bpm == 175.0
    assert "songbpm.com" in (meta.source_url or "")


@respx.mock
def test_lookup_returns_none_on_404() -> None:
    respx.get(url__regex=r"https://songbpm.com/.*").mock(return_value=httpx.Response(404))
    assert songbpm_com.lookup("No Song", "Nobody") is None


def test_slug_strips_punctuation() -> None:
    assert songbpm_com._slug("Earth, Wind & Fire") == "earth-wind-and-fire"
    assert songbpm_com._slug("Don't Stop") == "dont-stop"
