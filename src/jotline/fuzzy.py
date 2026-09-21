"""Subsequence matching for the pickers.

Every picker filters user-supplied text — note titles, tag names, workspace
names — so matching has to stay linear in the length of the candidate. Textual
ships `textual.fuzzy`, but it enumerates every possible set of match offsets:
the five-letter query "uoiea" against a 239-character line of repeated vowels
takes 1.3 seconds for a single candidate, and a six-letter one does not finish.
A picker runs the matcher over the whole note list on every keystroke, so that
is a freeze rather than a slow frame.

This module does two linear passes instead. The result is a slightly less
optimal set of offsets than exhaustive search would find, which costs nothing
in practice because picker labels are short.
"""
from __future__ import annotations

# Enough of a label to match against. Titles are short; the tail of a very long
# one is not what anyone is aiming at, and this bounds the work per keystroke.
CANDIDATE_LIMIT = 120

CONTIGUOUS_BONUS = 1.0
WORD_START_BONUS = 1.5
SUBSTRING_MULTIPLIER = 1.5
EXACT_MULTIPLIER = 2.0
# Small enough that it only separates otherwise equal matches.
LEADING_PENALTY = 0.02


def word_starts(candidate: str) -> frozenset[int]:
    """Offsets that begin a word, which a typed query most often aims at."""
    starts = set()
    previous_alphanumeric = False
    for index, character in enumerate(candidate):
        alphanumeric = character.isalnum()
        if alphanumeric and not previous_alphanumeric:
            starts.add(index)
        previous_alphanumeric = alphanumeric
    return frozenset(starts)


def _greedy(term: str, candidate: str) -> list[int] | None:
    """Earliest offsets matching term as a subsequence, or None."""
    offsets = []
    index = 0
    for character in term:
        found = candidate.find(character, index)
        if found == -1:
            return None
        offsets.append(found)
        index = found + 1
    return offsets


def _tighten(term: str, candidate: str, offsets: list[int]) -> list[int]:
    """Pull each offset as late as it can go, which groups the run together.

    The greedy pass finds the earliest match, so "note" against "no meeting
    notes" matches the leading "no" and then scatters. Walking back from the
    last offset and moving each character as late as it may sit recovers the
    contiguous "note" at the end. One pass, no backtracking.
    """
    tightened = list(offsets)
    limit = len(candidate)
    for position in range(len(term) - 1, -1, -1):
        found = candidate.rfind(term[position], tightened[position], limit)
        tightened[position] = found
        limit = found
    return tightened


def score_offsets(candidate: str, offsets: list[int], starts: frozenset[int]) -> float:
    """Reward contiguous runs and word starts, and prefer an earlier match."""
    score = float(len(offsets))
    previous = None
    for offset in offsets:
        if offset in starts:
            score += WORD_START_BONUS
        if previous is not None and offset == previous + 1:
            score += CONTIGUOUS_BONUS
        previous = offset
    return score - offsets[0] * LEADING_PENALTY


def match_term(term: str, candidate: str, starts: frozenset[int] | None = None) -> tuple[float, list[int]]:
    """Score one term against one candidate. `(0.0, [])` means no match.

    Both are expected to be case-folded already; the pickers fold once per
    keystroke rather than once per candidate.
    """
    if not term:
        return 0.0, []
    if starts is None:
        starts = word_starts(candidate)
    located = candidate.find(term)
    if located != -1:
        offsets = list(range(located, located + len(term)))
        multiplier = EXACT_MULTIPLIER if candidate == term else SUBSTRING_MULTIPLIER
        return score_offsets(candidate, offsets, starts) * multiplier, offsets
    offsets = _greedy(term, candidate)
    if offsets is None:
        return 0.0, []
    offsets = _tighten(term, candidate, offsets)
    return score_offsets(candidate, offsets, starts), offsets


def match(terms: list[str], candidate: str) -> tuple[float, list[int]]:
    """Score every term against one candidate, requiring all of them to match.

    Terms are combined the way the old substring filter combined them, so any
    query that matched before still matches; it may now also match when the
    letters are only in order.
    """
    folded = candidate.casefold()[:CANDIDATE_LIMIT]
    starts = word_starts(folded)
    total = 0.0
    found: set[int] = set()
    for term in terms:
        score, offsets = match_term(term, folded, starts)
        if not score:
            return 0.0, []
        total += score
        found.update(offsets)
    return total, sorted(found)
