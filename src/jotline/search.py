"""Small, literal query language shared by the UI, saved views and CLI."""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
import shlex
from typing import Protocol

DATE_FIELDS = ('created-after', 'created-before', 'updated-after', 'updated-before')
FIELDS = ('tag', 'title', *DATE_FIELDS)


class NoteQuery(Protocol):
    id: str
    body: str
    title: str
    tags: set[str]
    created: str
    updated: str


@dataclass(frozen=True)
class Term:
    field: str
    value: str
    excluded: bool


def parse_query(query: str) -> list[Term]:
    """Split a query into its terms, raising ValueError on an unusable date."""
    try:
        terms = shlex.split(query.casefold())
    except ValueError:
        # An unfinished quote is normal while typing in the live search field.
        terms = query.casefold().replace('"', '').split()
    predicates = []
    for term in terms:
        excluded = term.startswith('-') and len(term) > 1
        term = term[1:] if excluded else term
        field, separator, value = term.partition(':')
        if term.startswith('#'):
            field, value = 'tag', term[1:]
        elif not separator or field not in FIELDS:
            field, value = 'text', term
        if field in DATE_FIELDS:
            if value != 'today':
                try:
                    parsed = date.fromisoformat(value)
                    if parsed.isoformat() != value:
                        raise ValueError('Non-canonical date')
                except ValueError:
                    raise ValueError('Date filters use YYYY-MM-DD or today') from None
            else:
                value = date.today().isoformat()
        predicates.append(Term(field, value, excluded))
    return predicates


def compile_query(query: str) -> Callable[[NoteQuery], bool]:
    """A note predicate for a query of words, #tags, field:value terms and -exclusions."""
    predicates = parse_query(query)

    def matches(note):
        for field, value, excluded in ((t.field, t.value, t.excluded) for t in predicates):
            if field == 'tag':
                found = value in note.tags
            elif field == 'title':
                found = value in note.title.casefold()
            elif field == 'text':
                # Match IDs only by a meaningful prefix; short terms would
                # otherwise hit random hex digits in almost every note.
                found = value in note.body.casefold() or (len(value) >= 8 and note.id.startswith(value))
            else:
                attribute, direction = field.split('-')
                stamp = getattr(note, attribute)[:10]
                found = bool(stamp) and (stamp >= value if direction == 'after' else stamp <= value)
            if found == excluded:
                return False
        return True
    return matches


# Enough of a matched line to read in a 32-column sidebar, and enough room
# before the match that the word is not always flush against the ellipsis.
SNIPPET_WIDTH = 46
SNIPPET_LEAD = 12

TITLE_WEIGHT = 3.0
TAG_WEIGHT = 2.0
BODY_WEIGHT = 1.0
# A term near the top of a note is usually what the note is about.
POSITION_WEIGHT = 1.0


def sought(terms: list[Term]) -> list[str]:
    """The words a reader is actually looking for, ignoring filters."""
    return [term.value for term in terms
            if term.field in ('text', 'title') and not term.excluded and term.value]


@dataclass(frozen=True)
class Match:
    """Why a note came back, and where the reader can see it."""
    score: float
    line: str
    offsets: tuple[tuple[int, int], ...]


def rank(note: NoteQuery, terms: list[Term]) -> Match | None:
    """Score a matched note and pick a line showing one of the words.

    Returns None when the query has no words in it — a bare `#tag` or date
    filter matches every result equally, so there is nothing to rank or show.
    """
    words = sought(terms)
    if not words:
        return None
    title = note.title.casefold()
    body = note.body.casefold()
    score = 0.0
    for word in words:
        if word in title:
            score += TITLE_WEIGHT
        if word in note.tags:
            score += TAG_WEIGHT
        located = body.find(word)
        if located != -1:
            score += BODY_WEIGHT + POSITION_WEIGHT * (1.0 - located / (len(body) or 1))
    return Match(score, *excerpt(note.body, words, note.title))


def fold_origins(text: str) -> tuple[str, list[int]]:
    """Case-fold text, and map every folded index back to the index it came from.

    Folding is not length-preserving — ß folds to ss, ﬁ to fi, İ to i̇ — so an
    offset into the folded text is not an offset into the text itself. Anything
    that slices or marks the original has to come back through this map. Full
    case folding is defined per character, so folding character by character
    gives the same text as folding the whole string at once.
    """
    pieces, origins = [], []
    for index, character in enumerate(text):
        piece = character.casefold()
        pieces.append(piece)
        origins += [index] * len(piece)
    origins.append(len(text))
    return ''.join(pieces), origins


def folded_spans(text: str, words: list[str]) -> list[tuple[int, int]]:
    """Every occurrence of any word in text, ignoring case, as spans into text."""
    folded, origins = fold_origins(text)
    spans = []
    for word in words:
        index = folded.find(word)
        while index != -1:
            start = origins[index]
            # A word can end inside one source character's expansion, as "s"
            # does inside "ß". Mark the whole character rather than nothing.
            spans.append((start, max(origins[index + len(word)], start + 1)))
            index = folded.find(word, index + 1)
    return spans


def excerpt(body: str, words: list[str], title: str = '') -> tuple[str, tuple[tuple[int, int], ...]]:
    """The first body line holding one of the words, windowed around the match.

    A line that is only the note's own title heading is skipped, because the
    title is already on the row above and repeating it says nothing. Offsets
    are spans into the returned line, so a caller can mark the words without
    searching the text a second time.

    Lines are walked in order and folded one at a time, so every offset here
    is an offset into the body. Searching the whole folded body instead mixes
    the two coordinate systems, which on a note that grows when folded both
    quotes the wrong line and can fail to make progress at all.
    """
    heading = title.casefold().strip()
    start = 0
    while start <= len(body):
        stop = body.find('\n', start)
        if stop == -1:
            stop = len(body)
        line = body[start:stop]
        spans = folded_spans(line, words)
        if spans and not (heading and line.casefold().lstrip('# ').strip() == heading):
            return window(line, min(begin for begin, _ in spans), words)
        start = stop + 1
    return '', ()


def window(line: str, at: int, words: list[str]) -> tuple[str, tuple[tuple[int, int], ...]]:
    """Trim a line to the part around the match, marking each word in it."""
    left = max(0, at - SNIPPET_LEAD)
    right = left + SNIPPET_WIDTH
    windowed = line[left:right].strip()
    if left:
        windowed = '…' + windowed
    if right < len(line):
        windowed += '…'
    return windowed, tuple(sorted(folded_spans(windowed, words)))
