"""Wiki-link parsing and note connections, shared by store, preview, and CLI.

Highlighting and export already ignore ``[[links]]`` inside fenced code and
inline code spans. Indexing uses the same rules so documentation examples do
not become fake backlinks.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
import re
from typing import Callable, Iterator, Literal, Protocol
from urllib.parse import quote, unquote

from .limits import MAX_DERIVED_ITEMS
from .tasks import code_spans, fenced_pairs

LINK = re.compile(r"\[\[([^\[\]|]+)(?:\|([^\[\]]*))?\]\]")
SNIPPET_LIMIT = 80
WIKI_HREF_PREFIX = "jotline:"
LinkStatus = Literal["ok", "broken", "ambiguous"]


class LinkedNote(Protocol):
    id: str
    title: str
    heading: str
    body: str
    locked: bool


@dataclass(frozen=True)
class WikiLink:
    """One ``[[target]]`` or ``[[target|label]]`` outside fenced or inline code."""

    target: str
    label: str
    line: int
    column: int
    end_column: int
    snippet: str


@dataclass(frozen=True)
class LinkRef:
    """One incoming or outgoing connection, with enough context to open or create."""

    direction: str
    target: str
    snippet: str
    status: LinkStatus
    note_id: str | None = None
    title: str = ""

    def as_dict(self) -> dict[str, str | None]:
        return {
            "direction": self.direction,
            "id": self.note_id,
            "title": self.title,
            "target": self.target,
            "snippet": self.snippet,
            "status": self.status,
        }


@dataclass
class NoteConnections:
    incoming: list[LinkRef] = field(default_factory=list)
    outgoing: list[LinkRef] = field(default_factory=list)
    locked: bool = False

    @property
    def backlink_ids(self) -> list[str]:
        return [item.note_id for item in self.incoming if item.note_id and item.status == "ok"]


def snippet_text(line: str) -> str:
    text = " ".join(line.strip().split())
    return text if len(text) <= SNIPPET_LIMIT else text[: SNIPPET_LIMIT - 3] + "..."


def connection_mark(status: str) -> str:
    if status == "ok":
        return "→"
    if status == "ambiguous":
        return "?"
    if status == "broken":
        return "!"
    raise ValueError(f"unknown link status: {status}")


def wiki_href(target: str) -> str:
    """Preview-only href that opens a note without contacting a server."""
    return WIKI_HREF_PREFIX + quote(target, safe="")


def wiki_target_from_href(href: str) -> str | None:
    if not href.startswith(WIKI_HREF_PREFIX):
        return None
    return unquote(href.removeprefix(WIKI_HREF_PREFIX))


def _overlaps_code(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    index = bisect_right(spans, (start, end))
    return bool((index and spans[index - 1][1] > start)
                or (index < len(spans) and spans[index][0] < end))


def iter_wiki_links(body: str) -> Iterator[WikiLink]:
    """Yield wiki links that highlighting and export also treat as links."""
    if "[[" not in body:
        return
    pairs, fenced = fenced_pairs(body)
    for row, (content, _) in enumerate(pairs):
        if row in fenced or "[[" not in content:
            continue
        spans = code_spans(content)
        snippet = snippet_text(content)
        for match in LINK.finditer(content):
            if _overlaps_code(match.start(), match.end(), spans):
                continue
            yield WikiLink(
                target=match.group(1),
                label=(match.group(2) or "").strip(),
                line=row + 1,
                column=match.start(),
                end_column=match.end(),
                snippet=snippet,
            )


def wiki_link_targets(body: str) -> tuple[set[str], str]:
    values: set[str] = set()
    for index, link in enumerate(iter_wiki_links(body)):
        if index >= MAX_DERIVED_ITEMS:
            return values, f"Note has more than {MAX_DERIVED_ITEMS} links; results were truncated"
        values.add(link.target)
    return values, ""


def wiki_link_at(body: str, row: int, column: int) -> WikiLink | None:
    """The wiki link covering this editor cursor, if any.

    ``end_column`` is the regex end index, so a cursor sitting just after
    ``]]`` (as after an insert) still counts as on the link.
    """
    for link in iter_wiki_links(body):
        if link.line == row + 1 and link.column <= column <= link.end_column:
            return link
    return None


def rewrite_wiki_links(body: str, replace: Callable[[WikiLink, re.Match[str]], str]) -> str:
    """Rewrite wiki links outside code, leaving fences and code spans alone."""
    if "[[" not in body:
        return body
    pairs, fenced = fenced_pairs(body)
    result = []
    for row, (content, ending) in enumerate(pairs):
        if row not in fenced and "[[" in content:
            spans = code_spans(content)
            snippet = snippet_text(content)
            pieces, last = [], 0
            for match in LINK.finditer(content):
                if _overlaps_code(match.start(), match.end(), spans):
                    continue
                link = WikiLink(
                    target=match.group(1),
                    label=(match.group(2) or "").strip(),
                    line=row + 1,
                    column=match.start(),
                    end_column=match.end(),
                    snippet=snippet,
                )
                pieces.append(content[last:match.start()] + replace(link, match))
                last = match.end()
            content = "".join(pieces) + content[last:]
        result.append(content + ending)
    return "".join(result)


def stabilize_wiki_target(body: str, target: str, note: LinkedNote) -> str:
    """Rewrite ``[[target]]`` links to a stable ``[[id|label]]`` for ``note``."""

    def replace(link: WikiLink, match: re.Match[str]) -> str:
        if link.target != target:
            return match.group(0)
        label = link.label or note.title
        label = label.replace("|", " ").replace("[", "").replace("]", "")
        return f"[[{note.id}|{label}]]"

    return rewrite_wiki_links(body, replace)


def note_matches_target(note: LinkedNote, token: str) -> bool:
    return token.split('#^', 1)[0] in {note.id, note.title, note.heading}


def resolve_link_targets(notes: list[LinkedNote], token: str) -> list[LinkedNote]:
    return [note for note in notes if note_matches_target(note, token)]


def outgoing_refs(body: str, notes: list[LinkedNote]) -> list[LinkRef]:
    """Resolve each wiki link in ``body`` against notes already in the workspace."""
    refs: list[LinkRef] = []
    seen: set[tuple[str, str, str | None]] = set()
    for link in iter_wiki_links(body):
        matches = resolve_link_targets(notes, link.target)
        if not matches:
            key = ("outgoing", link.target, None)
            if key not in seen:
                seen.add(key)
                refs.append(LinkRef("outgoing", link.target, link.snippet, "broken"))
            continue
        status: LinkStatus = "ambiguous" if len(matches) > 1 else "ok"
        for note in matches:
            key = ("outgoing", link.target, note.id)
            if key in seen:
                continue
            seen.add(key)
            refs.append(LinkRef("outgoing", link.target, link.snippet, status, note.id, note.title))
    return refs


def incoming_refs(target: LinkedNote, notes: list[LinkedNote]) -> list[LinkRef]:
    """Notes that point at ``target`` by id, title, or heading."""
    keys = {target.id, target.title, target.heading}
    refs: list[LinkRef] = []
    for note in notes:
        if note.id == target.id:
            continue
        for link in iter_wiki_links(note.body):
            if link.target.split('#^', 1)[0] not in keys:
                continue
            refs.append(LinkRef("incoming", link.target, link.snippet, "ok", note.id, note.title))
            break
    return refs


def connect_note(target: LinkedNote, notes: list[LinkedNote], *, body: str | None = None) -> NoteConnections:
    """Incoming and outgoing connections for one note.

    Locked notes keep incoming links (others can still point at the id) but
    cannot show outgoing links until they are unlocked.
    """
    if target.locked:
        return NoteConnections(incoming=incoming_refs(target, notes), outgoing=[], locked=True)
    return NoteConnections(
        incoming=incoming_refs(target, notes),
        outgoing=outgoing_refs(body if body is not None else target.body, notes),
        locked=False,
    )
