"""Whole-word scanning stays linear without changing literal/Unicode semantics."""
import os
from pathlib import Path
import random
import re
import subprocess
import sys

import pytest

from jotline.markdown_editor import literal_matches, literal_pattern, whole_word_match


def reference_spans(pattern, body, start=0):
    """Simple overlapping search oracle, suitable only for small inputs."""
    start = max(start, 0)
    result = []
    while start <= len(body) and (match := pattern.search(body, start)) is not None:
        if whole_word_match(match):
            result.append(match.span())
            start = max(match.end(), match.start() + 1)
        else:
            start = match.start() + 1
    return result


def test_long_rejected_overlaps_and_near_misses_finish_in_bounded_time():
    # Keep this in a subprocess: the old repeated-search implementation can
    # otherwise hang the test suite. The budget includes interpreter startup
    # and imports, and is comfortably above the linear implementation's time.
    source = r'''
from jotline.markdown_editor import literal_matches, literal_pattern
body = 'a ' * 200000
query = 'a ' * 100000
for case_sensitive in (False, True):
    pattern = literal_pattern(query, case_sensitive=case_sensitive)
    assert [m.span() for m in literal_matches(pattern, body, whole_word=True)] == [(200000, 400000)]
    pattern = literal_pattern('a' * 100000 + 'b', case_sensitive=case_sensitive)
    assert list(literal_matches(pattern, 'a' * 400000, whole_word=True)) == []
'''
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [sys.executable, '-c', source], check=True, timeout=12,
        env={**os.environ, 'PYTHONPATH': str(root / 'src')}, capture_output=True, text=True,
    )


@pytest.mark.parametrize('query', [
    r'\n', r'\1', chr(92), r'\.*+?[](){}|^$', '\n', '\r\n', '\t', ' ', '\\\n',
    '\x00', 'İ', 'ı', 'ſ', 'K', 'ß', 'ẞ', 'Σ', 'ς', 'µ', 'μ', 'ﬅ', 'ﬆ', 'ΐ', 'ΐ',
])
@pytest.mark.parametrize('case_sensitive', [False, True])
def test_literal_escape_round_trip_and_original_match_context(query, case_sensitive):
    body = f'x{query}! {query} x{query}x ({query})'
    pattern = literal_pattern(query, case_sensitive=case_sensitive)
    matches = list(literal_matches(pattern, body, whole_word=True))
    assert [match.span() for match in matches] == reference_spans(pattern, body)
    for match in matches:
        assert isinstance(match, re.Match)
        assert match.string is body
        assert match[0] == body[match.start():match.end()]


def test_case_insensitive_equivalence_keeps_original_character_offsets():
    body = 'İ ı I i ſ S K k ß ẞ ss Σ σ ς µ Μ μ ﬅ ﬆ st'
    for query in ('i', 's', 'k', 'ß', 'ss', 'σ', 'μ', 'ﬅ', 'st'):
        pattern = literal_pattern(query)
        assert [match.span() for match in literal_matches(pattern, body, whole_word=True)] == reference_spans(
            pattern, body)


def test_randomized_unicode_literal_scan_matches_overlapping_regex_oracle():
    randomizer = random.Random(104729)
    alphabet = 'aABb _+\n\r\t\\[]().*?字中\u0301İıſsKkßẞΣσςµΜμﬅﬆ'
    for _ in range(5000):
        body = ''.join(randomizer.choices(alphabet, k=randomizer.randrange(60)))
        if body and randomizer.randrange(2):
            begin = randomizer.randrange(len(body))
            query = body[begin:begin + randomizer.randrange(1, 10)]
        else:
            query = ''.join(randomizer.choices(alphabet, k=randomizer.randrange(10)))
        pattern = literal_pattern(query, case_sensitive=bool(randomizer.randrange(2)))
        start = randomizer.randrange(-2, len(body) + 3)
        assert [match.span() for match in literal_matches(
            pattern, body, whole_word=True, start=start)] == reference_spans(pattern, body, start)


@pytest.mark.parametrize('start', [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11])
def test_overlapping_case_equivalent_prefixes_and_document_boundaries(start):
    body = 'xİ ı I i İ ı I i !'
    pattern = literal_pattern('i I i')
    assert [match.span() for match in literal_matches(
        pattern, body, whole_word=True, start=start)] == reference_spans(pattern, body, start)
