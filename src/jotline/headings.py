"""One heading index for editor navigation, previews and exported documents.

Fragments are decoded at the href boundary, never here. Wiki link targets are
plain text (``wiki_target_from_href`` already decodes the transport once).
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from urllib.parse import quote

from markdown_it.token import Token


@dataclass(frozen=True)
class Heading:
    row: int
    level: int
    title: str
    slug: str


def heading_slug(title: str) -> str:
    """Unicode-aware, deterministic fragment stem (not URL-encoded)."""
    title = unicodedata.normalize("NFC", title.casefold())
    stem = "".join(character for character in title
                   if character.isspace() or character in "_-"
                   or unicodedata.category(character)[0] in "LMN")
    stem = re.sub(r"\s+", "-", stem.strip()) or "section"
    # Footnotes own this namespace, even when this particular note has none.
    return "section-" + stem if stem.startswith("jl-footnote-") else stem


def _inline_text(tokens: list[Token]) -> str:
    pieces = []
    footnote_reference = False
    for token in tokens:
        if token.type == "link_open" and (token.attrGet("id") or "").startswith("jl-footnote-ref-"):
            # These captions are generated numbering, not heading text. Adding
            # an earlier footnote must not silently rename an existing anchor.
            footnote_reference = True
        elif footnote_reference:
            if token.type == "link_close":
                footnote_reference = False
        elif token.type in {"text", "code_inline"}:
            pieces.append(token.content)
        elif token.type in {"softbreak", "hardbreak"}:
            pieces.append(" ")
        elif token.type == "image":
            pieces.append(_inline_text(token.children or []))
        elif token.children:
            pieces.append(_inline_text(token.children))
    return "".join(pieces)


def _heading_tokens(tokens: list[Token]):
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and index + 1 < len(tokens):
            inline = tokens[index + 1]
            if inline.type == "inline":
                yield token, _inline_text(inline.children or [])


def add_heading_ids(tokens: list[Token]) -> list[Heading]:
    """Assign globally unique IDs to parsed headings, including duplicate stems."""
    used: set[str] = set()
    next_suffix: dict[str, int] = {}
    found = []
    for token, title in _heading_tokens(tokens):
        stem = heading_slug(title)
        slug = stem
        suffix = next_suffix.get(stem, 1)
        while slug in used:
            slug = f"{stem}-{suffix}"
            suffix += 1
        next_suffix[stem] = suffix
        used.add(slug)
        token.attrSet("id", slug)
        found.append(Heading((token.map or [0])[0], int(token.tag[1:]), title, slug))
    return found


def heading_index(body: str) -> list[Heading]:
    # Import here lets the parser reuse add_heading_ids without an import cycle.
    from .export import printable_markdown
    from .rendering import markdown_parser

    tokens = markdown_parser().parse(printable_markdown(body, followable=True))
    return [Heading((token.map or [0])[0], int(token.tag[1:]), title, token.attrGet("id") or "")
            for token, title in _heading_tokens(tokens)]


def resolve_heading(body: str, fragment: str) -> Heading | None:
    """Find an exact slug, then a human-readable heading. Never URL-decode."""
    found = heading_index(body)
    if exact := next((heading for heading in found if heading.slug == fragment), None):
        return exact
    stem = heading_slug(fragment)
    return next((heading for heading in found if heading.slug == stem), None)


def heading_choices(found: list[Heading]) -> list[tuple[str, str]]:
    return [(heading.slug, "  " * (heading.level - 1)
             + (heading.title or "(untitled heading)") + f" · line {heading.row + 1}")
            for heading in found]


def heading_href(slug: str) -> str:
    return "#" + quote(slug, safe="-_")
