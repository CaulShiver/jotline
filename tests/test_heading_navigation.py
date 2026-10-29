"""Heading anchors share source positions, IDs and safe navigation boundaries."""
import re
from unittest.mock import Mock

import pytest
from textual.widgets import Markdown

from jotline.app import Jotline
from jotline.export import printable_markdown, render_html
from jotline.headings import heading_index, heading_slug, resolve_heading
from jotline.links import resolve_link_targets, wiki_href, wiki_target_from_href
from jotline.modal import Palette
from jotline.rendering import PreviewMarkdown
from jotline.screens import MarkdownPreview
from jotline.store import Vault


def test_canonical_headings_ignore_code_and_include_setext_nested_and_inline_text():
    body = ('# Hello *world* and `code`\n\n'
            '```markdown\n# Hidden\n```\n\n'
            '    # Indented code\n\n'
            'Setext\n------\n\n> ## Quoted\n\n- ### Nested\n')
    found = heading_index(body)
    assert [(h.row, h.level, h.title, h.slug) for h in found] == [
        (0, 1, 'Hello world and code', 'hello-world-and-code'),
        (8, 2, 'Setext', 'setext'), (11, 2, 'Quoted', 'quoted'), (13, 3, 'Nested', 'nested')]
    exported = render_html('Example', body)
    assert re.findall(r'<h[1-6] id="([^"]+)"', exported) == [h.slug for h in found]


def test_unicode_normalization_duplicate_collisions_and_empty_headings():
    body = '# Café\n# Cafe\u0301\n# Café-1\n# CAFÉ\n# 東京 日本\n# !!!\n#\n# jl-footnote-1\n'
    found = heading_index(body)
    assert [h.slug for h in found] == [
        'café', 'café-1', 'café-1-1', 'café-2', '東京-日本', 'section', 'section-1', 'section-jl-footnote-1']
    assert resolve_heading(body, 'CAFÉ').row == 0
    assert resolve_heading(body, 'café-1').row == 1
    assert resolve_heading(body, 'café%2D1') is None
    assert heading_slug('Straße & Über') == 'strasse-über'


def test_heading_wiki_labels_are_literal_and_ids_do_not_depend_on_title_lookup():
    body = '# [[some-id]]\n# [[other|*literal* C#]]\n'
    expected = [h.slug for h in heading_index(body)]
    html = render_html('Example', body, {'some-id': 'Renamed *title*'})
    assert re.findall(r'<h[1-6] id="([^"]+)"', html) == expected == ['some-id', 'literal-c']
    assert '*literal* C#' in html
    preview = printable_markdown(body, {'some-id': 'Renamed *title*'}, followable=True)
    assert [h.slug for h in heading_index(preview)] == expected


def test_footnote_and_heading_ids_have_disjoint_namespaces():
    html = render_html('Example', '# jl-footnote-1\n\nReference[^a]\n\n[^a]: Note\n')
    ids = re.findall(r' id="([^"]+)"', html)
    assert len(ids) == len(set(ids))
    assert {'section-jl-footnote-1', 'jl-footnote-1', 'jl-footnote-ref-1'} <= set(ids)


def test_renumbering_footnotes_does_not_rename_headings():
    body = '# Title[^a]\n\n[^a]: Heading source\n'
    changed = 'Earlier[^b]\n\n' + body + '\n[^b]: Another source\n'
    assert [(heading.title, heading.slug) for heading in heading_index(body)] == [('Title', 'title')]
    assert [(heading.title, heading.slug) for heading in heading_index(changed)] == [('Title', 'title')]
    assert '<h1 id="title">' in render_html('Example', changed)


def test_heading_connections_and_exact_titles_containing_hash(tmp_path):
    vault = Vault(tmp_path)
    target = vault.new('# Target\n\n## Section')
    prefix = vault.new('# C')
    exact = vault.new('# C#')
    for note in (target, prefix, exact):
        vault.save(note)
    source = vault.new(f'# Source\n[[{target.id}#Section]]\n[[#Source]]')
    vault.save(source)
    refs = vault.connections(source).outgoing
    assert len(refs) == 1 and refs[0].note_id == target.id and refs[0].status == 'ok'
    assert [note.id for note in vault.backlinks(target)] == [source.id]
    assert resolve_link_targets([prefix, exact], 'C#') == [exact]


async def test_editor_toc_uses_parser_and_returns_focus_by_keyboard(tmp_path):
    app = Jotline(Vault(tmp_path))
    body = '# Root\n\n```\n# Hidden\n```\n\nSection\n---\n'
    async with app.run_test(size=(80, 24)) as pilot:
        app.editor().load_text(body)
        await pilot.pause()
        app.action_outline()
        await pilot.pause()
        assert isinstance(app.screen, Palette)
        assert len(app.screen.choices) == 2
        await pilot.press(*'Section', 'enter')
        await pilot.pause()
        assert app.editor().cursor_location == (6, 0)
        assert app.focused is app.editor()
        assert app.editor().text == body


async def test_preview_contents_and_fragments_are_local_and_decode_once(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    source = vault.new('# Root\n\n## Café\n\n## Café\n\n> ### Nested\n')
    vault.save(source)
    app = Jotline(vault, initial_note=source)
    opened = Mock()
    monkeypatch.setattr(app, 'open_url', opened)
    async with app.run_test(size=(80, 24)) as pilot:
        app.action_preview()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, MarkdownPreview)
        markdown = screen.query_one(PreviewMarkdown)
        assert markdown.goto_anchor('café-1')
        assert markdown.goto_anchor('nested')
        assert not markdown.goto_anchor('missing')
        routed = []
        real_goto = markdown.goto_anchor
        monkeypatch.setattr(markdown, 'goto_anchor', lambda fragment: routed.append(fragment) or real_goto(fragment))
        for href in ('#caf%C3%A9-1', '#caf%25C3%25A9', 'https://example.invalid/#root', '//example.invalid/#root',
                     'file:///etc/passwd#root', 'javascript:alert(1)', 'jotline://example.invalid/#root'):
            markdown.post_message(Markdown.LinkClicked(markdown, href))
            await pilot.pause()
        # jotline:// is a local, unresolved wiki target; it must never open a URL.
        assert routed[:2] == ['café-1', 'caf%C3%A9']
        assert not opened.called
        # Reopen after the intentionally unresolved jotline target dismissed the modal.
        if app.screen is not screen:
            if isinstance(app.screen, Palette):
                await pilot.press('escape')
            app.action_preview()
            await pilot.pause()
            screen = app.screen
        await pilot.press('ctrl+t')
        await pilot.pause()
        assert isinstance(app.screen, Palette)
        await pilot.press(*'Nested', 'enter')
        await pilot.pause()
        assert app.screen is screen
        assert app.focused.id == 'markdown-scroll'
        await pilot.press('escape')
        await pilot.pause()
        assert app.current.id == source.id
        assert app.focused is app.editor()


async def test_live_preview_internal_href_and_external_safety(tmp_path, monkeypatch):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        app.editor().load_text('# Root\n## Café\n')
        app.action_live_preview()
        app.refresh_live_preview()
        await pilot.pause()
        markdown = app.query_one('#live-markdown', PreviewMarkdown)
        routed = Mock(return_value=True)
        monkeypatch.setattr(markdown, 'goto_anchor', routed)
        opened = Mock()
        monkeypatch.setattr(app, 'open_url', opened)
        for href in ('#caf%C3%A9', '#caf%25C3%25A9', 'https://example.invalid/#root'):
            markdown.post_message(Markdown.LinkClicked(markdown, href))
            await pilot.pause()
        assert [call.args[0] for call in routed.call_args_list] == ['café', 'caf%C3%A9']
        assert not opened.called


async def test_wiki_heading_navigation_connections_and_literal_percent(tmp_path):
    vault = Vault(tmp_path)
    target = vault.new('# Target\n\n## Café\n\n## Café\n\n## Rate%20Done\n')
    vault.save(target)
    source = vault.new(f'# Source\n[[{target.id}#Café]]\n[[{target.id}#café-1]]')
    vault.save(source)
    app = Jotline(vault, initial_note=source)
    async with app.run_test(size=(100, 35)) as pilot:
        target_text = f'{target.id}#Rate%20Done'
        assert wiki_target_from_href(wiki_href(target_text)) == target_text
        app.action_preview()
        await pilot.pause()
        markdown = app.screen.query_one(PreviewMarkdown)
        markdown.post_message(Markdown.LinkClicked(markdown, wiki_href(target_text)))
        await pilot.pause()
        assert app.current.id == target.id and app.editor().cursor_location == (6, 0)
        app.follow_wiki_target('#café-1')
        assert app.editor().cursor_location == (4, 0)
        app.load_id(source.id)
        app.action_backlinks()
        await pilot.pause()
        assert isinstance(app.screen, Palette)
        assert any(key == f'follow:{target.id}#café-1' for key, _ in app.screen.choices)
        await pilot.press(*'café-1', 'enter')
        await pilot.pause()
        assert app.current.id == target.id and app.editor().cursor_location == (4, 0)


@pytest.mark.parametrize('same_note', [False, True])
async def test_failed_save_cannot_navigate_to_heading(tmp_path, monkeypatch, same_note):
    vault = Vault(tmp_path)
    target = vault.new('# Target\n\n## Section\n')
    source = vault.new('# Source\n\n## Section\n')
    vault.save(target)
    vault.save(source)
    app = Jotline(vault, initial_note=source)
    async with app.run_test(size=(100, 35)) as pilot:
        app.editor().load_text(source.body + 'Unsaved draft\n')
        app.editor().move_cursor((0, 0))
        monkeypatch.setattr(vault, 'save', Mock(side_effect=OSError('disk full')))
        app.follow_wiki_target(('#' if same_note else target.id + '#') + 'Section')
        await pilot.pause()
        assert app.current.id == source.id
        assert app.editor().cursor_location == (0, 0)
        assert 'Unsaved draft' in app.editor().text and app.dirty


async def test_stale_heading_target_moved_workspace_does_not_crash_or_open(tmp_path):
    vault = Vault(tmp_path)
    target = vault.new('# Target\n\n## Section\n')
    source = vault.new('# Source\n')
    vault.save(target)
    vault.save(source)
    app = Jotline(vault, initial_note=source)
    async with app.run_test(size=(100, 35)) as pilot:
        app.cached_link_targets()
        moved = vault.read(target.id)
        moved.workspace = 'other'
        vault.save(moved)
        app.follow_wiki_target('Target#Section')
        await pilot.pause()
        assert app.current.id == source.id and app.workspace == 'default'
