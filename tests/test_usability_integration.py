from dataclasses import replace

from textual.widgets import Static, TextArea

from jotline.action_history import ActionHistory
from jotline.action_ui import ActionEditor
from jotline.app import Jotline, Palette, TextPrompt
from jotline.filesystem import fs
from jotline.recovery_ui import RecoveryScreen
from jotline.store import Vault


async def test_first_action_run_offers_starter_recipes(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        app.command('actions')
        await pilot.pause()
        assert isinstance(app.screen, Palette)
        assert 'starter recipe' in app.screen.heading
        assert any(key == 'append-and-archive' for key, _ in app.screen.choices)
        assert not app.settings.actions
        await pilot.press('escape')


async def test_visible_actions_and_import_are_keyboard_reachable(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press('ctrl+f')
        await pilot.click('#nav-actions')
        assert isinstance(app.screen, Palette)
        await pilot.press(*'build', 'enter')
        await pilot.pause()
        assert isinstance(app.screen, ActionEditor)
        focused = app.focused
        await pilot.press('tab')
        assert app.focused is not focused
        original_id = app.current.id
        await pilot.press('ctrl+n')
        assert app.current.id == original_id
        await pilot.press('escape')
        await pilot.click('#nav-import')
        assert isinstance(app.screen, TextPrompt)
        await pilot.press('escape')
        assert app.current.id == original_id


async def test_autosave_conflict_opens_comparison_once_and_cancel_keeps_draft(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('original')
    vault.save(note)
    app = Jotline(vault, initial_note=note)
    async with app.run_test() as pilot:
        app.autosave_timer.stop()
        app.query_one('#editor', TextArea).load_text('my draft')
        external = vault.read(note.id)
        external.body = 'their edit'
        vault.save(external)
        assert not app.save_current()
        await pilot.pause()
        assert isinstance(app.screen, RecoveryScreen)
        depth = len(app.screen_stack)
        app.autosave()
        assert len(app.screen_stack) == depth
        await pilot.press('escape')
        app.autosave()
        assert not isinstance(app.screen, RecoveryScreen)
        assert app.query_one('#editor', TextArea).text == 'my draft'
        assert app.dirty and vault.read(note.id).body == 'their edit'


async def test_action_committed_warning_updates_editor_and_records_outcome(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    source = vault.new('source')
    vault.save(source)
    app = Jotline(vault, initial_note=source)
    async with app.run_test() as pilot:
        app.autosave_timer.stop()
        app.settings = replace(app.settings, actions={'upper': [{'type': 'uppercase'}]})
        real_save, real_fsync = vault.save, fs.fsync

        def save_then_fail(working):
            baseline = working.original

            def fail_committed(fd):
                if working.original != baseline:
                    raise OSError('directory durability check failed')
                return real_fsync(fd)

            with monkeypatch.context() as context:
                context.setattr(fs, 'fsync', fail_committed)
                real_save(working)

        monkeypatch.setattr(vault, 'save', save_then_fail)
        app.run_local_action('upper')
        await pilot.pause()
        assert app.query_one('#editor', TextArea).text == vault.read(source.id).body == 'SOURCE'
        assert app.current.original == vault.read(source.id).original
        assert not app.dirty
        assert 'durability warning' in str(app.query_one('#status', Static).render())
        assert ActionHistory(tmp_path).read()[-1]['status'] == 'committed-with-warning'


async def test_saved_action_output_uses_storage_limit_not_insertion_reserve(tmp_path, monkeypatch):
    import jotline.workflows as workflows
    vault = Vault(tmp_path)
    note = vault.new('source')
    vault.save(note)
    app = Jotline(vault, initial_note=note)
    async with app.run_test() as pilot:
        app.settings = replace(app.settings, actions={'upper': [{'type': 'uppercase'}]})
        monkeypatch.setattr(workflows, 'EDIT_LIMIT_BYTES', 1)
        app.run_local_action('upper')
        await pilot.pause()
        assert app.query_one('#editor', TextArea).text == 'SOURCE'
        assert app.current.body == vault.read(note.id).body == 'SOURCE'
        assert not app.dirty


async def test_live_preview_serializes_content_and_cursor_updates(tmp_path, monkeypatch):
    import asyncio
    from textual.containers import VerticalScroll
    from textual.widgets import Markdown

    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        app.autosave_timer.stop()
        editor = app.query_one('#editor', TextArea)
        editor.load_text('\n\n'.join(f'Block {i}' for i in range(150)))
        editor.move_cursor((0, 0))
        app.command('live-preview')
        await app.workers.wait_for_complete()
        await pilot.pause()
        started = asyncio.Event()
        update = Markdown.update

        async def slow_update(widget, text):
            if widget.id == 'live-markdown':
                started.set()
                await asyncio.sleep(0.5)
            await update(widget, text)

        monkeypatch.setattr(Markdown, 'update', slow_update)
        await pilot.press('x')
        await asyncio.wait_for(started.wait(), timeout=5)
        # Dispatch a cursor-only update while the older content worker is asleep.
        app.query_one('#editor', TextArea).move_cursor(app.query_one('#editor', TextArea).document.end)
        await pilot.pause(0.35)
        assert app._live_preview_ratio == 1.0
        await app.workers.wait_for_complete()
        pane = app.query_one('#live-preview', VerticalScroll)
        # Scrolling is posted after layout refresh, outside the render workers.
        for _ in range(20):
            await pilot.pause(0.05)
            if pane.max_scroll_y > 0 and pane.scroll_y == pane.max_scroll_y:
                break
        assert pane.max_scroll_y > 0
        assert pane.scroll_y == pane.max_scroll_y
        assert 'xBlock 0' in app._live_preview_text


async def test_live_preview_resize_and_disable_while_compact(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        app.command('live-preview')
        await pilot.pause()
        pane = app.query_one('#live-preview')
        await pilot.resize_terminal(70, 20)
        await pilot.pause()
        assert app.compact_layout and pane.has_class('hidden')
        await pilot.resize_terminal(120, 40)
        await pilot.pause()
        assert not app.compact_layout and not pane.has_class('hidden')
        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        app.command('live-preview')
        await pilot.pause()
        assert not app.live_preview
        await pilot.resize_terminal(120, 40)
        await pilot.pause()
        assert pane.has_class('hidden')


async def test_live_preview_refreshes_externally_renamed_link(tmp_path):
    vault = Vault(tmp_path)
    target = vault.new('# Old title')
    vault.save(target)
    source = vault.new(f'See [[{target.id}]]\n\nLast line')
    vault.save(source)
    app = Jotline(vault, initial_note=source)
    async with app.run_test(size=(120, 40)) as pilot:
        app.autosave_timer.stop()
        app.command('live-preview')
        await app.workers.wait_for_complete()
        assert 'See Old title' in app._live_preview_text
        external = Vault(tmp_path)
        renamed = external.read(target.id)
        renamed.body = '# New title'
        external.save(renamed)
        await pilot.pause(1.05)
        await pilot.press(*['down'] * 10)
        assert app.query_one('#editor', TextArea).cursor_location[0] == 2
        await pilot.pause(0.4)
        await app.workers.wait_for_complete()
        assert 'See New title' in app._live_preview_text
        assert 'Old title' not in app._live_preview_text


async def test_empty_note_selection_explains_why_apply_stays_open(tmp_path, monkeypatch):
    from jotline.workflows import SelectNotes

    vault = Vault(tmp_path)
    vault.save(vault.new('A note'))
    app = Jotline(vault)
    async with app.run_test() as pilot:
        app.select_bulk()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SelectNotes)
        messages = []
        monkeypatch.setattr(screen, 'notify', lambda message, **kwargs: messages.append(message))
        await pilot.press('ctrl+s')
        assert app.screen is screen
        assert messages == ['Select at least one note first']
