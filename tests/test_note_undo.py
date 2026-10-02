from jotline.app import Jotline
from jotline.markdown_editor import UndoStash
from jotline.store import Vault


def saved(vault, body):
    note = vault.new(body)
    vault.save(note)
    return note


async def type_at_end(app, pilot, text):
    editor = app.editor()
    editor.move_cursor(editor.document.end)
    await pilot.press(*text)
    await pilot.pause()


async def test_switching_notes_keeps_each_notes_undo(tmp_path):
    vault = Vault(tmp_path)
    first, second, third = saved(vault, '# First'), saved(vault, '# Second'), saved(vault, '# Third')
    app = Jotline(vault, initial_note=first)
    async with app.run_test() as pilot:
        editor = app.editor()
        await type_at_end(app, pilot, ' one')
        app.load_id(second.id)
        await type_at_end(app, pilot, ' two')
        app.load_id(first.id)
        await pilot.pause()
        assert editor.text == '# First one'
        await pilot.press('ctrl+z')
        assert editor.text == '# First'
        await pilot.press('ctrl+z')
        assert editor.text == '# First'
        await pilot.press('ctrl+y')
        assert editor.text == '# First one'
        app.load_id(third.id)
        await pilot.press('ctrl+z')
        assert editor.text == '# Third'
        app.load_id(second.id)
        await pilot.press('ctrl+z')
        assert editor.text == '# Second'
        assert app.save_current()
        assert vault.read(first.id).body == '# First one'
        assert vault.read(second.id).body == '# Second'


async def test_external_change_drops_the_stashed_undo(tmp_path):
    vault = Vault(tmp_path)
    first, second = saved(vault, '# First'), saved(vault, '# Second')
    app = Jotline(vault, initial_note=first)
    async with app.run_test() as pilot:
        editor = app.editor()
        await type_at_end(app, pilot, ' one')
        app.load_id(second.id)
        await pilot.pause()
        outside = Vault(tmp_path).read(first.id)
        outside.body = 'Rewritten elsewhere'
        Vault(tmp_path).save(outside)
        app.vault.invalidate_cache()
        app.load_id(first.id)
        await pilot.pause()
        assert editor.text == 'Rewritten elsewhere'
        await pilot.press('ctrl+z')
        assert editor.text == 'Rewritten elsewhere'
        assert first.id not in app.undo_stash.entries


async def test_reloading_the_same_note_keeps_undo_only_for_identical_text(tmp_path):
    vault = Vault(tmp_path)
    note = saved(vault, 'start')
    app = Jotline(vault, initial_note=note)
    async with app.run_test() as pilot:
        editor = app.editor()
        await type_at_end(app, pilot, '!')
        assert app.save_current()
        app.load(vault.read(note.id))
        await pilot.press('ctrl+z')
        assert editor.text == 'start'
        await pilot.press('ctrl+y')
        assert app.save_current()
        changed = vault.read(note.id)
        changed.body = 'start!\n- [x] ticked'
        vault.save(changed)
        app.load(vault.read(note.id))
        await pilot.press('ctrl+z')
        assert editor.text == 'start!\n- [x] ticked'


async def test_trashing_a_note_forgets_its_undo(tmp_path):
    vault = Vault(tmp_path)
    first, second = saved(vault, '# First'), saved(vault, '# Second')
    app = Jotline(vault, initial_note=first)
    async with app.run_test() as pilot:
        await type_at_end(app, pilot, ' one')
        app.load_id(second.id)
        assert first.id in app.undo_stash.entries
        app.move_context_note(vault.read(first.id), collection='trash')
        assert first.id not in app.undo_stash.entries


async def test_undo_stash_keeps_only_recent_notes(tmp_path):
    vault = Vault(tmp_path)
    app = Jotline(vault)
    async with app.run_test():
        editor = app.editor()
        stash = UndoStash(size=2)
        for key in 'abc':
            editor.load_text('')
            editor.insert(key)
            stash.keep(key, editor)
            assert not editor.history.undo_stack
        assert list(stash.entries) == ['b', 'c']
        editor.load_text('b')
        assert not stash.restore('c', editor) and 'c' not in stash.entries
        assert stash.restore('b', editor)
        editor.undo()
        assert editor.text == ''
        editor.load_text('')
        stash.keep('empty', editor)
        assert 'empty' not in stash.entries
