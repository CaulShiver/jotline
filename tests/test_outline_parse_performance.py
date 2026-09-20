"""Differential coverage for the deliberately narrow flat-list fast path."""
import random
from unittest.mock import patch

import pytest

import jotline.outliner as model
from jotline.outliner import Outline


def structure(outline):
    blocks = list(outline.walk())
    indices = {block: index for index, block in enumerate(blocks)}
    rows = outline.rows()
    return (outline.text, outline.newline, [
        (block.lines, block.content, block.prefix, block.indent, block.slot,
         indices.get(block.parent), [indices[child] for child in block.children], rows[block])
        for block in blocks
    ])


def authoritative(text):
    with patch.object(model, '_plain_flat_list', return_value=False):
        return Outline(text)


@pytest.mark.parametrize('ending', ['\n', '\r\n', '\r'])
@pytest.mark.parametrize('trailing', ['', 'one'])
@pytest.mark.parametrize('labels', [
    ['A', 'B'], ['1', '2'], ['1. nested', '2) nested'],
    ['1. ```', '2. <script>', '3. > quoted'],
    ['漢字', 'éclair', 'Ⅳ', '²'],
    ['A **strong**', 'B `inline`', 'C [link](target)', 'D [[note#^block]]'],
    ['A\ttext', 'B  ', 'C\x00text', 'D\u2028text', 'E\u0085text'],
])
def test_flat_fast_path_matches_commonmark(ending, trailing, labels):
    text = ending.join('- ' + label for label in labels) + (ending if trailing else '')
    expected = structure(authoritative(text))
    with patch.object(model.PARSER, 'parse', side_effect=AssertionError('Unexpected parser fallback')):
        assert structure(Outline(text)) == expected


@pytest.mark.parametrize('text', [
    '', '\n', '- ', '-\n- A', '- A\n\n- B', '- A\n\n', '- A\n  ',
    '-  A', '- \tA', '- [ ] Task', '- [x] Done', '- **bold**', '- `code`',
    '- ---\n- B', '- ```\n  - literal\n  ```', '- <script>\n- literal',
    '- > Quote\n- B', '- # Heading\n- B', '- - Same line\n  - Nested',
    '- A\n  - Child', '- A\n  continuation', ' - A\n - B', '\t- A',
    '+ A\n+ B', '* A\n* B', '1. A\n2. B', 'Paragraph\n- A',
    '- A\n<!-- comment -->\n- B', '- A\n# Heading',
])
def test_nonflat_or_structural_syntax_uses_authoritative_parser(text):
    expected = structure(authoritative(text))
    with patch.object(model.PARSER, 'parse', wraps=model.PARSER.parse) as parse:
        assert structure(Outline(text)) == expected
        parse.assert_called_once_with(text)


def test_generated_flat_lists_match_commonmark_with_mixed_endings():
    rng = random.Random(50712)
    starts = ['A', 'z', '0', '1', '9', '漢', 'é', 'Ⅳ', '²']
    fragments = ['', ' text', '. ', ') ', ' ', '\t', '- ', '* ', '> ',
                 '```', '~~~', '[x]', '[a]: url', '<script>', '</script>',
                 '<!--', '-->', '^anchor', '\x00', '\u2028', '\u0085']
    for _ in range(300):
        lines = ['- ' + rng.choice(starts) + ''.join(rng.choices(fragments, k=4))
                 for _ in range(rng.randint(1, 12))]
        text = lines[0]
        for line in lines[1:]:
            text += rng.choice(['\n', '\r', '\r\n']) + line
        text += rng.choice(['', '\n', '\r', '\r\n'])
        assert structure(Outline(text)) == structure(authoritative(text))


def test_large_flat_fast_path_preserves_terminal_blank_line_and_last_row():
    text = '\n'.join(f'- Item {index}' for index in range(10_000)) + '\n'
    with patch.object(model.PARSER, 'parse', side_effect=AssertionError('Unexpected parser fallback')):
        outline = Outline(text)
    assert outline.text == text
    assert len(outline.roots) == 10_000
    assert outline.roots[-1].lines == ['- Item 9999', '']
    assert outline.row(outline.roots[-1]) == 9999
