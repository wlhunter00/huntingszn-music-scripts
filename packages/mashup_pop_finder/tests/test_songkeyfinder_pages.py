import httpx
import respx

from mashup_pop_finder import songkeyfinder


def _listing_html(songs: list[tuple[str, str]]) -> str:
    rows = "".join(
        f"<tr><td><a href='/artists/{a}'>{a}</a></td>"
        f"<td><a href='/songs/1/{a}+{t}'>{t}</a></td><td>1</td></tr>"
        for t, a in songs
    )
    return f"<table class='searchresults'><tr><th>Artist</th><th>Song</th></tr>{rows}</table>"


@respx.mock
def test_list_songs_fetches_multiple_pages() -> None:
    # Register paginated URL before the base URL (respx can treat base as a prefix).
    respx.get("https://songkeyfinder.com/songs-in-key/b-minor?page=2").mock(
        return_value=httpx.Response(
            200,
            text=_listing_html([("Three", "Art3")]),
        )
    )
    respx.get("https://songkeyfinder.com/songs-in-key/b-minor").mock(
        return_value=httpx.Response(
            200,
            text=_listing_html([("One", "Art1"), ("Two", "Art2")]),
        )
    )
    out = songkeyfinder.list_songs_in_key("B minor", limit=10, pages=2)
    assert [c.title for c in out] == ["One", "Two", "Three"]


@respx.mock
def test_list_songs_stops_at_limit_across_pages() -> None:
    respx.get("https://songkeyfinder.com/songs-in-key/a-major?page=2").mock(
        return_value=httpx.Response(200, text=_listing_html([("C", "Z")])),
    )
    respx.get("https://songkeyfinder.com/songs-in-key/a-major").mock(
        return_value=httpx.Response(200, text=_listing_html([("A", "X"), ("B", "Y")])),
    )
    out = songkeyfinder.list_songs_in_key("A major", limit=2, pages=3)
    assert len(out) == 2
    assert {c.title for c in out} == {"A", "B"}


def test_pages_for_limit() -> None:
    assert songkeyfinder.pages_for_limit(1) == 1
    assert songkeyfinder.pages_for_limit(30) == 1
    assert songkeyfinder.pages_for_limit(31) == 2
    assert songkeyfinder.pages_for_limit(90) == 3
