"""Independent synthetic probes for the combined search/Markdown upgrades."""
from html.parser import HTMLParser
import random
import re

import pytest
from textual.widgets import Markdown

from jotline.app import Jotline
from jotline.export import render_html
from jotline.headings import heading_index
from jotline.links import incoming_refs, outgoing_refs, wiki_href
from jotline.markdown_editor import literal_matches, literal_pattern, whole_word_match
from jotline.outliner_ui import OutlinerScreen
from jotline.rendering import PreviewMarkdown, markdown_parser
from jotline.store import Vault


class _Document(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def test_literal_unicode_offsets_match_a_simple_overlapping_reference():
    rng = random.Random(7781)
    alphabet = 'aABb \u0301_+\n中İıiIſsSKkKßẞΣσς\\[](){}.*?^$\t\r\x00😀'
    for _ in range(2500):
        body = ''.join(rng.choices(alphabet, k=rng.randrange(0, 90)))
        query = ''.join(rng.choices(alphabet, k=rng.randrange(0, 10)))
        pattern = literal_pattern(query, case_sensitive=bool(rng.randrange(2)))
        start = rng.randrange(-3, len(body) + 5)
        expected = []
        pos = max(0, start)
        while pos <= len(body):
            match = pattern.search(body, pos)
            if match is None:
                break
            if whole_word_match(match):
                expected.append(match.span())
                pos = max(match.end(), match.start() + 1)
            else:
                pos = match.start() + 1
        actual = [match.span() for match in literal_matches(pattern, body, whole_word=True, start=start)]
        assert actual == expected, (body, query, start)


@pytest.mark.parametrize('uri', [
    'javascript:alert(1)', 'java&#x73;cript:alert(1)', 'vbscript:msgbox(1)',
    'data:text/html,%3Cscript%3Ealert(1)%3C/script%3E', 'file:///synthetic/not-read',
    'https://example.invalid/"onclick="x', '//example.invalid/x', 'jotline:../../outside',
    '#<svg/onload=1>',
])
def test_footnotes_headings_and_image_labels_cannot_inject_active_html(uri):
    body = (f'# [Heading]({uri})\n\nHere[^a\"onclick=\"x].\n\n'
            f'[^a\"onclick=\"x]: ![image]({uri}) [link]({uri}) <script>bad</script>')
    output = markdown_parser().render(body)
    document = _Document(output)
    assert not {'img', 'script', 'iframe', 'object', 'embed'} & {tag for tag, _ in document.tags}
    assert all(not key.lower().startswith('on') for _, attrs in document.tags for key in attrs)
    assert all(not attrs.get('href', '').lower().startswith(
        ('javascript:', 'vbscript:', 'file:', 'data:text/html')) for _, attrs in document.tags)
    assert '&lt;script&gt;bad&lt;/script&gt;' in output


def test_literal_html_and_footnote_heading_wiki_ids_match_export_title_lookup():
    body = ('<div>\n# [[abcdef]]\n</div>\n\nReference[^x]\n\n'
            '[^x]: ## [[other]]\n')
    expected = [heading.slug for heading in heading_index(body)]
    output = render_html('Synthetic', body, {'abcdef': 'Renamed title', 'other': 'Different title'})
    assert re.findall(r'<h[1-6] id="([^"]+)"', output) == expected == ['abcdef', 'other']


def test_exact_hash_note_title_does_not_create_a_backlink_to_its_prefix(tmp_path):
    vault = Vault(tmp_path)
    prefix = vault.new('# C')
    exact = vault.new('# C#')
    source = vault.new('# Source\n[[C#]]')
    notes = [prefix, exact, source]
    for note in notes:
        vault.save(note)
    assert incoming_refs(prefix, notes) == []
    assert [ref.note_id for ref in incoming_refs(exact, notes)] == [source.id]
    assert [ref.note_id for ref in outgoing_refs(source.body, notes)] == [exact.id]


def test_many_heading_collisions_and_footnote_refs_have_unique_resolving_ids():
    # Large enough to exercise duplicate suffix allocation and repeated refs,
    # without wall-clock assertions or resource-dependent test deadlines.
    body = ''.join(f'# jl-footnote-{index}\n# Café\n# Café-{index}\n' for index in range(1, 101))
    body += '\n' + 'Reference[^x] ' * 300 + '\n\n[^x]: Synthetic body.\n'
    document = _Document(markdown_parser().render(body))
    ids = [attrs['id'] for _, attrs in document.tags if 'id' in attrs]
    fragments = [attrs['href'][1:] for _, attrs in document.tags if attrs.get('href', '').startswith('#')]
    assert len(ids) == len(set(ids))
    assert set(fragments) <= set(ids)
    assert len([ident for ident in ids if ident.startswith('jl-footnote-ref-')]) == 300


@pytest.mark.parametrize('body', [
    'A[^x]\n\n[^unused]: Unused with another[^x]\n\n[^x]: Body.',
    'A[^x]\n\n[^x]: Superseded[^y]\n\n[^x]: Replacement.\n\n[^y]: Unreachable body.',
    'A\n\n[^unused]: Unused with another[^x]\n\n[^x]: Unreachable body.',
    'A[^x]\n\n[^x]: Reachable[^y]\n\n[^y]: Cycle back[^x]',
    '![A ![B[^x]](https://example.invalid/b)](https://example.invalid/a)\n\n[^x]: Body.',
])
def test_discarded_footnote_definitions_do_not_create_orphan_backlinks(body):
    output = markdown_parser().render(body)
    document = _Document(output)
    ids = [attrs['id'] for _, attrs in document.tags if 'id' in attrs]
    fragments = [attrs['href'][1:] for _, attrs in document.tags if attrs.get('href', '').startswith('#')]
    assert len(ids) == len(set(ids))
    assert set(fragments) <= set(ids)
    assert 'Unreachable body.' not in output


async def test_heading_navigation_flushes_queued_outline_text_before_switching(tmp_path):
    vault = Vault(tmp_path)
    source = vault.new('# Source\n\n- Original block\n')
    target = vault.new('# Target\n\n## Destination\n')
    vault.save(source)
    vault.save(target)
    app = Jotline(vault, initial_note=source)
    async with app.run_test(size=(100, 35)) as pilot:
        app.autosave_timer.stop()
        app.action_outliner()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, OutlinerScreen)
        block = next(block for block in screen.outline.walk() if block.content.rstrip() == 'Original block')
        screen.choose(block)
        screen.action_edit_block()
        # No pause: TextArea.Changed is queued when navigation begins.
        screen.block_editor().load_text('Queued synthetic edit')
        app.follow_wiki_target(f'{target.id}#destination')
        await pilot.pause()
        assert 'Queued synthetic edit' in vault.read(source.id).body
        assert app.current.id == target.id
        assert isinstance(app.screen, OutlinerScreen)
        assert '## Destination' in app.screen.current.content


async def test_rendered_wiki_heading_event_keeps_a_literal_percent_sequence(tmp_path):
    vault = Vault(tmp_path)
    source = vault.new('# Source\n')
    target = vault.new('# Target\n\n## Rate Done\n\n## Rate%20Done\n')
    vault.save(source)
    vault.save(target)
    app = Jotline(vault, initial_note=source)
    async with app.run_test(size=(100, 35)) as pilot:
        app.action_preview()
        await pilot.pause()
        markdown = app.screen.query_one(PreviewMarkdown)
        href = wiki_href(f'{target.id}#Rate%20Done')
        markdown.post_message(Markdown.LinkClicked(markdown, href))
        await pilot.pause()
        assert app.current.id == target.id
        assert app.editor().cursor_location == (4, 0)
