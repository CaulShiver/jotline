"""Semantic guards for the metadata paths exercised while typing."""
import io
import random
import re

import pytest

from jotline import store
from jotline.store import Note, TAG, tagged_body


def test_literal_tag_prefix_preserves_unicode_and_boundary_rules():
    previous = re.compile(r'(?<![\w#])#([\w][\w/-]*)', re.UNICODE)
    samples = [
        '#work #WORK #next/action #a-b #_private #équipe #東京',
        'word#hidden ##heading ###hidden # visible #/bad #-bad #',
        '#one#two (#three)\n#four\r#five\t#six',
    ]
    randomizer = random.Random(714)
    alphabet = 'abcXYZ09_#/ -\n\r\t()é東\u0301\u2003'
    samples.extend(''.join(randomizer.choices(alphabet, k=300)) for _ in range(100))
    for body in samples:
        expected = [(match.span(), match.group(1)) for match in previous.finditer(body)]
        assert [(match.span(), match.group(1)) for match in TAG.finditer(body)] == expected
        assert Note('note', body).tags == {value.casefold() for _, value in expected}


@pytest.mark.parametrize('body', [
    '', '\n\n', ' \t\r\n# Heading\r\nbody', '###', '  ### Heading ###  \nbody',
    '\t# Tab before heading\nbody', '\u2003\n# Unicode heading é\nbody',
    'one\rtwo\nthree', '\v# Heading\fnext\nbody', 'a' * 1000 + '\nbody',
])
def test_heading_keeps_existing_line_and_whitespace_semantics(body):
    expected = 'Untitled'
    for line in io.StringIO(body):
        if line.strip():
            expected = line.lstrip('# ').strip() or 'Untitled'
            break
    note = Note('note', body)
    assert note.heading == expected
    assert note.title == expected[:100]
    note.sealed = 'sealed'
    assert note.heading == 'Encrypted note (locked)'


def test_metadata_updates_immediately_after_body_edit():
    note = Note('note', '# Before\n#work')
    assert note.title == 'Before' and note.tags == {'work'}
    note.body = '\n# After\n#home'
    assert note.title == 'After' and note.tags == {'home'}
    note.body = '- Untagged outline item'
    assert note.title == '- Untagged outline item' and note.tags == set()


def test_tag_budget_counts_matches_and_retains_warning(monkeypatch):
    monkeypatch.setattr(store, 'MAX_DERIVED_ITEMS', 2)
    note = Note('note', '#repeat #repeat #later')
    assert note.tags == {'repeat'}
    assert note.derived_warnings == ['Note has more than 2 tags; results were truncated']
    assert note.tags == {'repeat'}
    assert len(note.derived_warnings) == 1
    with pytest.raises(ValueError, match='truncated'):
        tagged_body(note.body, 'new')
