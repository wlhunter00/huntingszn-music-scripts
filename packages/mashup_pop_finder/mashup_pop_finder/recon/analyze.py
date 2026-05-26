"""Inspect saved HTML files and surface candidate selectors.

Pure parsing — no network. Testable in isolation.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from selectolax.parser import HTMLParser, Node

_KEY_TEXT_RE = re.compile(
    r"\b([A-G][#b♯♭]?)\s*(major|minor|maj|min)\b",
    re.IGNORECASE,
)
_BPM_TEXT_RE = re.compile(r"\b(\d{2,3})\b\s*(?:bpm|tempo)", re.IGNORECASE)
_BPM_LABEL_RE = re.compile(r"\b(?:bpm|tempo)\b\s*[:=]?\s*(\d{2,3})\b", re.IGNORECASE)


@dataclass(frozen=True)
class SelectorHit:
    selector: str
    text: str
    matched: str


@dataclass
class FileAnalysis:
    path: Path
    title: str | None
    n_tags: int
    top_tags: list[tuple[str, int]]
    top_classes: list[tuple[str, int]]
    repeating_blocks: list[tuple[str, int]]  # (selector, count)
    key_hits: list[SelectorHit]
    bpm_hits: list[SelectorHit]

    def best_guess_block(self) -> str:
        """A copy-pasteable selectors.py snippet based on what we found."""
        lines = [f"# from {self.path.name}"]
        if self.key_hits:
            lines.append(f'SONG_PAGE_KEY_SELECTOR = "{self.key_hits[0].selector}"')
        if self.bpm_hits:
            lines.append(f'SONG_PAGE_BPM_SELECTOR = "{self.bpm_hits[0].selector}"')
        if self.repeating_blocks:
            sel, _ = self.repeating_blocks[0]
            lines.append(f'LISTING_ROW_SELECTOR = "{sel}"')
        return "\n".join(lines)


def _node_selector(node: Node) -> str:
    tag = node.tag or ""
    attrs = node.attributes or {}
    cls = attrs.get("class")
    nid = attrs.get("id")
    if nid:
        return f"{tag}#{nid}"
    if cls:
        primary = cls.strip().split()[0] if cls.strip() else ""
        return f"{tag}.{primary}" if primary else tag
    return tag


def _title_of(tree: HTMLParser) -> str | None:
    node = tree.css_first("title")
    if node is None or not node.text():
        return None
    return node.text().strip()


def _walk(tree: HTMLParser) -> Iterator[Node]:
    if tree.root is None:
        return
    yield from tree.root.traverse(include_text=False)


def _top_tag_counts(tree: HTMLParser, limit: int = 15) -> list[tuple[str, int]]:
    c: Counter[str] = Counter()
    for n in _walk(tree):
        if n.tag:
            c[n.tag] += 1
    return c.most_common(limit)


def _top_class_counts(tree: HTMLParser, limit: int = 20) -> list[tuple[str, int]]:
    c: Counter[str] = Counter()
    for n in _walk(tree):
        cls = (n.attributes or {}).get("class")
        if not cls:
            continue
        for token in cls.strip().split():
            c[token] += 1
    return c.most_common(limit)


def _repeating_blocks(tree: HTMLParser, min_count: int = 4) -> list[tuple[str, int]]:
    """Find class names that appear on many sibling-like elements — likely
    listing rows."""
    counts: Counter[str] = Counter()
    for n in _walk(tree):
        if not n.tag or n.tag in {"script", "style", "meta", "link", "head"}:
            continue
        cls = (n.attributes or {}).get("class")
        if cls:
            for token in cls.strip().split():
                counts[f"{n.tag}.{token}"] += 1
        if n.tag in {"tr", "li"}:
            counts[n.tag] += 1
    return [(sel, n) for sel, n in counts.most_common(20) if n >= min_count]


_SKIP_TAGS = {"script", "style", "head", "meta", "html", "body"}


def _collect_hits(
    tree: HTMLParser,
    pattern_callable: Callable[[str], re.Match[str] | None],
    limit: int,
) -> list[SelectorHit]:
    raw: list[SelectorHit] = []
    for n in _walk(tree):
        if not n.tag or n.tag in _SKIP_TAGS:
            continue
        text = (n.text() or "").strip()
        if not text or len(text) > 200:
            continue
        m = pattern_callable(text)
        if m:
            raw.append(SelectorHit(_node_selector(n), text, m.group(0)))
    # Prefer narrowest containing text — that's the leaf where the value
    # actually lives, not the wrapping div/section.
    raw.sort(key=lambda h: (len(h.text), h.selector))
    return raw[:limit]


def _find_key_hits(tree: HTMLParser, limit: int = 10) -> list[SelectorHit]:
    return _collect_hits(tree, _KEY_TEXT_RE.search, limit)


def _find_bpm_hits(tree: HTMLParser, limit: int = 10) -> list[SelectorHit]:
    return _collect_hits(
        tree, lambda t: _BPM_LABEL_RE.search(t) or _BPM_TEXT_RE.search(t), limit
    )


def analyze_html(path: Path, html: str) -> FileAnalysis:
    tree = HTMLParser(html)
    return FileAnalysis(
        path=path,
        title=_title_of(tree),
        n_tags=sum(1 for _ in _walk(tree)),
        top_tags=_top_tag_counts(tree),
        top_classes=_top_class_counts(tree),
        repeating_blocks=_repeating_blocks(tree),
        key_hits=_find_key_hits(tree),
        bpm_hits=_find_bpm_hits(tree),
    )


def render_summary(analyses: list[FileAnalysis]) -> str:
    out: list[str] = ["# Recon summary", ""]
    if not analyses:
        out.append("_No HTML files found in input directory._")
        return "\n".join(out)
    for a in analyses:
        out.append(f"## `{a.path.name}`")
        out.append("")
        out.append(f"- Title: `{a.title or '(none)'}`")
        out.append(f"- Tag count: {a.n_tags}")
        out.append(f"- Top tags: {', '.join(f'{t}({n})' for t, n in a.top_tags[:8])}")
        out.append(
            f"- Top classes: {', '.join(f'{t}({n})' for t, n in a.top_classes[:8]) or '(none)'}"
        )
        out.append("")
        if a.repeating_blocks:
            out.append("**Likely listing rows:**")
            for sel, n in a.repeating_blocks[:5]:
                out.append(f"  - `{sel}` x {n}")
            out.append("")
        if a.key_hits:
            out.append("**Candidate key selectors:**")
            for h in a.key_hits[:5]:
                out.append(f"  - `{h.selector}` → matched `{h.matched}` in `{_truncate(h.text)}`")
            out.append("")
        if a.bpm_hits:
            out.append("**Candidate BPM selectors:**")
            for h in a.bpm_hits[:5]:
                out.append(f"  - `{h.selector}` → matched `{h.matched}` in `{_truncate(h.text)}`")
            out.append("")
        guess = a.best_guess_block()
        if guess.strip():
            out.append("**Best-guess `selectors.py` block:**")
            out.append("")
            out.append("```python")
            out.append(guess)
            out.append("```")
            out.append("")
    return "\n".join(out)


def _truncate(s: str, n: int = 80) -> str:
    s = s.replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def run(input_dir: Path) -> tuple[list[FileAnalysis], str]:
    analyses: list[FileAnalysis] = []
    for p in sorted(input_dir.glob("*.html")):
        try:
            html = p.read_text(encoding="utf-8")
        except OSError:
            continue
        analyses.append(analyze_html(p, html))
    summary_md = render_summary(analyses)
    (input_dir / "SUMMARY.md").write_text(summary_md, encoding="utf-8")
    return analyses, summary_md
