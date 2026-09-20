"""Malformed imported Markdown must not monopolize parsing or highlighting."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

import jotline.tasks
from jotline.links import iter_wiki_links, rewrite_wiki_links
from jotline.markdown_editor import HIGHLIGHT_MAX_LINE_CHARS, highlight_line
from jotline.tasks import code_spans


@pytest.mark.parametrize(('text', 'expected'), [
    ('before `one` after ``two ` inner``', ['`one`', '``two ` inner``']),
    ('``unmatched [[visible]]`', []),
    ('`unmatched [[visible]]``', []),
    ('`` [[hidden]] ``` still hidden `` [[visible]]', ['`` [[hidden]] ``` still hidden ``']),
    ('``` unmatched `` [[hidden]] ``', ['`` [[hidden]] ``']),
    ('`first\nsecond`', []),
    ('````', []),
])
def test_code_spans_match_complete_runs(text, expected):
    assert [text[start:end] for start, end in code_spans(text)] == expected


def test_code_spans_never_start_in_a_delimiter_suffix():
    assert code_spans('``text`', 1) == []


def test_link_rewriting_and_highlighting_share_code_delimiters():
    text = '`` [[hidden]] ``` also hidden `` [[visible]]'
    assert [link.target for link in iter_wiki_links(text)] == ['visible']
    assert rewrite_wiki_links(text, lambda link, match: link.target.upper()) == (
        '`` [[hidden]] ``` also hidden `` VISIBLE'
    )
    spans = highlight_line(text)
    assert [text[start:end] for start, end, kind in spans if kind == 'inline_code'] == [
        '`` [[hidden]] ``` also hidden ``'
    ]
    assert [text[start:end] for start, end, kind in spans if kind == 'md.wikilink'] == ['[[visible]]']


def test_highlighter_keeps_long_lines_plain_without_truncating_text():
    line = '[unclosed ' + '[' * HIGHLIGHT_MAX_LINE_CHARS
    assert highlight_line(line) == []
    assert highlight_line('[' * HIGHLIGHT_MAX_LINE_CHARS) == []
    assert highlight_line(' ' * (HIGHLIGHT_MAX_LINE_CHARS - 2) + '|x') == []
    assert any(kind == 'link.uri' for _, _, kind in highlight_line('[normal](https://example.test)'))


@pytest.mark.parametrize('kind', ['backticks', 'brackets', 'many-spans', 'emphasis'])
def test_malformed_markdown_finishes_in_a_bounded_subprocess(kind):
    # A timeout kills a regressed parser, rather than hanging the whole suite.
    program = r'''
import sys
from jotline.links import iter_wiki_links, rewrite_wiki_links
from jotline.markdown_editor import highlight_line
kind = sys.argv[1]
if kind == 'backticks':
    body = 'prefix ' + '`' * 100_000 + ' [[visible]]'
    assert [link.target for link in iter_wiki_links(body)] == ['visible']
    assert rewrite_wiki_links(body, lambda link, match: 'DONE').endswith(' DONE')
elif kind == 'many-spans':
    body = ('`[[hidden]]` [[visible]] ' * 10_000).rstrip()
    assert len(list(iter_wiki_links(body))) == 10_000
    result = rewrite_wiki_links(body, lambda link, match: 'DONE')
    assert result.count('DONE') == 10_000 and result.count('[[hidden]]') == 10_000
else:
    body = '[' * 100_000 if kind == 'brackets' else '**a ' * 25_000
assert highlight_line(body) == []
'''
    # pytest's pythonpath setting is process-local. Explicitly reuse the loaded
    # source tree even when this interpreter has another editable checkout.
    environment = os.environ.copy()
    source_root = str(Path(jotline.tasks.__file__).resolve().parents[1])
    environment['PYTHONPATH'] = os.pathsep.join(filter(None, [source_root, environment.get('PYTHONPATH')]))
    result = subprocess.run([sys.executable, '-c', program, kind], capture_output=True, text=True,
                            timeout=5, check=False, env=environment)
    assert result.returncode == 0, result.stderr
