import pytest
from textual.widgets import Input, Static

from jotline.app import Jotline
from jotline.limits import EDIT_LIMIT_BYTES
from jotline.messages import failed, key_name
from jotline.navigation import ViewEditor
from jotline.preferences import Preferences
from jotline.review_ui import INBOX_CLEAR
from jotline.screens import FindInNote
from jotline.settings import Settings, ShortcutError
from jotline.store import Vault


def notifications(app):
    return [item.message for item in app._notifications]


def test_failure_wording_keeps_the_os_reason_and_names_the_next_step():
    error = PermissionError(13, 'Permission denied', '/vault/.jotline-backups')
    assert failed('Backup failed', error, 'Try again.') == \
        'Backup failed: Permission denied: /vault/.jotline-backups. Try again.'
    assert failed('Tags were not added', ValueError('Enter tags separated by spaces.')) == \
        'Tags were not added: Enter tags separated by spaces.'
    assert [key_name(key) for key in ('ctrl+n', 'alt+k', 'f1', 'ctrl+shift+up', '')] == \
        ['Ctrl+N', 'Alt+K', 'F1', 'Ctrl+Shift+Up', '']


async def test_view_names_get_their_own_rule(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 40)) as pilot:
        app.save_view('Weekly Review')
        await pilot.pause()
        [message] = notifications(app)
        assert 'View names need 1–48 lowercase letters' in message and 'Workspace' not in message
        app.save_view_prompt()
        await pilot.pause()
        form = app.screen
        assert isinstance(form, ViewEditor)
        form.query_one('#view-name', Input).value = 'Bad Name'
        await pilot.click('#view-save')
        error = str(form.query_one('#view-error', Static).render())
        assert error.startswith('View names need') and 'Workspace' not in error


async def test_size_limit_messages_give_the_limit_in_megabytes(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        assert not app.insert_editor_text('x' * (EDIT_LIMIT_BYTES + 1))
        await pilot.pause()
        assert any('10 MB size limit' in message for message in notifications(app))


async def test_finished_action_says_what_changed_and_export_uses_the_title(tmp_path):
    Settings(actions={'shout': [{'type': 'uppercase'}],
                      'share': [{'type': 'uppercase'}, {'type': 'export'}, {'type': 'restore'}]}
             ).save(tmp_path / '.jotline-settings.json')
    vault = Vault(tmp_path)
    note = vault.new('plan the week')
    vault.save(note)
    app = Jotline(vault, initial_note=note)
    async with app.run_test() as pilot:
        app.run_local_action('shout')
        await pilot.pause()
        assert notifications(app)[-1] == 'Ran “shout” on “PLAN THE WEEK”: 1 step applied, text changed'
        app.run_local_action('share')
        await pilot.pause()
        exported, finished = notifications(app)[-2:]
        assert exported == 'Saved the action output as a new inbox note, “PLAN THE WEEK”'
        assert finished == 'Ran “share” on “PLAN THE WEEK”: 3 steps applied, note text unchanged'


async def test_outliner_merge_refusal_says_why_and_what_to_do(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(110, 35)) as pilot:
        app.editor().load_text('- [x] shipped\n- next')
        await pilot.pause()
        app.action_outliner()
        await pilot.pause()
        screen = app.screen
        screen.current = screen.outline.roots[1]
        screen.action_merge()
        await pilot.pause()
        message = notifications(app)[-1]
        assert message.startswith('Not merged: joining a finished task') and 'block above' in message
        assert len(screen.outline.roots) == 2


async def test_block_reference_says_whether_the_note_is_missing_or_ambiguous(tmp_path):
    vault = Vault(tmp_path)
    for _ in range(2):
        vault.save(vault.new('Twin\n- block ^abc'))
    app = Jotline(vault)
    async with app.run_test() as pilot:
        app.follow_wiki_target('Twin#^abc')
        app.follow_wiki_target('Nowhere#^abc')
        await pilot.pause()
        ambiguous, missing = notifications(app)[-2:]
        assert '“Twin”' in ambiguous and 'matches 2 notes' in ambiguous
        assert '“Nowhere”' in missing and 'is not a note in this workspace' in missing


async def test_inbox_clear_reads_the_same_from_both_commands(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        app.action_process_inbox()
        app.open_next_inbox_capture()
        await pilot.pause()
        assert notifications(app) == [INBOX_CLEAR, INBOX_CLEAR]


@pytest.mark.parametrize(('text', 'expected'), [('one a', 'Replaced 1 match ·'), ('a a a', 'Replaced 3 matches ·')])
async def test_replace_count_is_singular_or_plural(tmp_path, text, expected):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(110, 35)) as pilot:
        app.editor().load_text(text)
        app.push_screen(FindInNote())
        await pilot.pause()
        find = app.screen
        find.query_one('#find-query', Input).value = 'a'
        find.query_one('#replace-value', Input).value = 'b'
        await pilot.pause()
        find.replace_matches(all_matches=True)
        assert str(find.query_one('#find-status', Static).render()).startswith(expected)


def test_shortcut_errors_name_the_command_and_the_key():
    with pytest.raises(ShortcutError) as caught:
        Settings(outline_hotkeys={'fold': 'ctrl+n'}).validate()
    assert str(caught.value) == 'Ctrl+N is assigned to both New thought and Fold or expand branch (outliner)'
    assert caught.value.field == 'outline-hotkey-fold'
    with pytest.raises(ShortcutError, match=r'^Fold or expand branch \(outliner\): Ctrl\+A is reserved'):
        Settings(outline_hotkeys={'fold': 'ctrl+a'}).validate()
    with pytest.raises(ShortcutError, match=r'^Alt\+Q is assigned to both Previous outline location \(outliner\) '
                                            r'and Fold or expand branch \(outliner\)$'):
        Settings(outline_hotkeys={'nav_back': 'alt+q', 'fold': 'alt+q'}).validate()
    with pytest.raises(ShortcutError, match=r'^Save note: Ctrl\+A is reserved') as caught:
        Settings(hotkeys={'save': 'ctrl+a'}).validate()
    assert caught.value.field == 'hotkey-save'


async def test_preferences_mark_the_offending_shortcut_and_show_outliner_defaults(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.press('ctrl+comma')
        prefs = app.screen
        assert isinstance(prefs, Preferences)
        fold = prefs.query_one('#outline-hotkey-fold', Input)
        assert fold.placeholder == 'Default: Ctrl+Space'
        assert prefs.query_one('#outline-hotkey-move_to', Input).placeholder == 'No default key · in the menu'
        fold.value = 'ctrl+n'
        await pilot.press('ctrl+s')
        assert app.screen is prefs
        assert 'Fold or expand branch (outliner)' in str(prefs.query_one('#preferences-error', Static).render())
        assert prefs.focused is fold and fold.has_class('-invalid')
        fold.value = ''
        await pilot.press('ctrl+s')
        assert app.screen is not prefs


async def test_shortcut_text_uses_one_key_style_everywhere(tmp_path):
    vault = Vault(tmp_path)
    target = vault.new('Target note')
    vault.save(target)
    source = vault.new('Source [[Target note]]')
    vault.save(source)
    app = Jotline(vault, initial_note=source)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert 'Ctrl+P commands · Ctrl+D daily log' in str(app.query_one('#hint', Static).render())
        brand = str(app.query_one('#brand', Static).render())
        assert 'Ctrl+T tags' in brand
        assert 'workspaces' not in brand
        app.connections()
        assert 'Alt+K connections' in str(app.query_one('#connections', Static).render())
        assert dict(app.command_choices())['new'].endswith(' · Ctrl+N')


async def test_delete_in_the_note_list_moves_the_note_to_trash(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('Old idea')
    vault.save(note)
    app = Jotline(vault)
    async with app.run_test(size=(110, 35)) as pilot:
        await pilot.pause()
        listing = app.query_one('#notes')
        listing.focus()
        listing.highlighted = next(index for index in range(listing.option_count)
                                   if listing.get_option_at_index(index).id == note.id)
        await pilot.press('delete')
        await pilot.pause()
        assert vault.read(note.id).collection == 'inbox'
        assert 'Move to Trash? Enter' in str(listing.get_option_at_index(listing.highlighted).prompt)
        await pilot.press('escape')
        assert vault.read(note.id).collection == 'inbox'
        listing.focus()
        await pilot.press('delete', 'enter')
        await pilot.pause()
        assert vault.read(note.id).collection == 'trash'
        assert notifications(app)[-1] == 'Moved “Old idea” to Trash. Restore it from Show trash.'
        app.command('view:trash')
        await pilot.pause()
        listing.focus()
        listing.highlighted = 0
        await pilot.press('delete', 'enter')
        await pilot.pause()
        assert vault.read(note.id).collection == 'trash'
        assert notifications(app)[-1].startswith('“Old idea” is already in Trash.')
