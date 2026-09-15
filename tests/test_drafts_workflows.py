from datetime import date
import json
import subprocess
import sys

import pytest
from textual.widgets import Input, TextArea, SelectionList
from jotline.app import Jotline, Palette
from jotline.workflows import Arrange, SelectNotes
from jotline.markdown_editor import headings
from jotline.settings import Settings
from jotline.store import Vault
from jotline.templates import Templates
from jotline.actions import run_action


def saved(vault, body, workspace='default'):
    note = vault.new(body, workspace=workspace)
    vault.save(note)
    return note


async def wait_for_command_palette(app, pilot):
    editor = app.query_one('#editor', TextArea)
    for _ in range(40):
        if isinstance(app.screen, Palette):
            return
        await pilot.pause(0.05)
    offset = editor.char_offset(editor.cursor_location, editor.text)
    raise AssertionError(
        'command palette did not open: '
        f'screen={type(app.screen).__name__} focus={editor.has_focus} '
        f'selected={editor.selected_text!r} '
        f'trigger={editor.text[max(0, offset - 2):offset]!r}'
    )


def test_search_phrases_exclusions_fields_and_dates(tmp_path):
    vault = Vault(tmp_path)
    one = saved(vault, '# Red parachute\n#work\nBlue sky')
    saved(vault, '# Red and blue parachute\n#home')
    assert [n.id for n in vault.search('"red parachute" #work -green')] == [one.id]
    assert not vault.search('"red parachute" -blue')
    assert [n.id for n in vault.search('title:"red parachute" tag:work updated-after:today')] == [one.id]
    assert not vault.search('created-before:2000-01-01')
    assert vault.search('"red')  # incomplete live query is usable
    with pytest.raises(ValueError):
        vault.search('updated-after:banana')


def test_templates_context_includes_and_cycles(tmp_path):
    templates = Templates(tmp_path)
    templates.save('part', '{{title}} {{selection}} {{date:%Y}}')
    templates.save('full', '{{template:part}} {{body}} {{unknown}}')
    assert templates.render('full', 'default', title='T', selection='S', body='{{title}}') == f'T S {date.today().year} {{{{title}}}} {{{{unknown}}}}'
    templates.save('cycle', '{{template:cycle}}')
    with pytest.raises(ValueError, match='recursive'):
        templates.render('cycle', 'default')
    with pytest.raises(ValueError):
        templates.render_text('{{template:../escape}}', 'default')


def test_heading_parser_excludes_fenced_code():
    assert headings('# One\n```md\n# Hidden\n```\nTwo\n---\n~~~\n# Nope\n~~~\n## Three'.split('\n')) == [(0, 1, 'One'), (4, 2, 'Two'), (9, 2, 'Three')]


async def test_replace_all_is_literal_and_one_undo(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        editor = app.query_one('#editor', TextArea)
        editor.insert('Café café\nCAfÉ')
        await pilot.pause()
        app.command('find')
        await pilot.pause()
        app.screen.query_one('#find-query', Input).value = 'café'
        app.screen.query_one('#replace-value', Input).value = r'\1'
        await pilot.pause()
        app.screen.replace_matches(all_matches=True)
        assert editor.text == '\\1 \\1\n\\1'
        await pilot.press('escape', 'ctrl+z')
        assert editor.text == 'Café café\nCAfÉ'
        app.command('find')
        await pilot.pause()
        app.screen.query_one('#find-query', Input).value = 'café'
        await pilot.pause()
        app.screen.case_sensitive = True
        app.screen.query_one('#replace-value', Input).value = 'tea'
        app.screen.replace_matches(all_matches=True)
        assert editor.text == 'Café tea\nCAfÉ'


async def test_navigation_insert_template_and_arrange_undo(tmp_path):
    vault = Vault(tmp_path)
    one = saved(vault, '# One\nline\n## End')
    two = saved(vault, '# Two')
    Templates(tmp_path).save('snippet', 'hello {{title}}')
    app = Jotline(vault)
    async with app.run_test() as pilot:
        editor = app.query_one('#editor', TextArea)
        app.load_id(one.id)
        editor.move_cursor((1, 2))
        app.load_id(two.id)
        app.previous_note()
        assert app.current.id == one.id and editor.cursor_location == (1, 2)
        app.jump_to_row('2')
        assert editor.cursor_location == (2, 0)
        app.insert_template_named('snippet')
        assert 'hello One' in editor.text
        await pilot.press('ctrl+z')
        assert editor.text == one.body
        app.arrange(False)
        await pilot.pause()
        assert isinstance(app.screen, Arrange)
        await pilot.press('alt+down', 'ctrl+s')
        assert editor.text == 'line\n# One\n## End'
        await pilot.press('ctrl+z')
        assert editor.text == one.body
        app.arrange(True)
        await pilot.pause()
        await pilot.press('ctrl+d', 'escape')
        assert editor.text == one.body


async def test_saved_view_restart_and_workspace_scope(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test():
        app.collection = 'archive'
        app.query_one('#search', Input).value = '#work -blocked'
        app.theme = 'rose-pine-dawn'
        app.view_sort = 'title'
        app.save_view('review')
        app.clear_view()
        app.apply_view('review')
        assert app.collection == 'archive' and app.theme == 'rose-pine-dawn'
        assert app.view_sort == 'title'
        app.switch_workspace('other')
        app.apply_view('review')
        assert app.collection == 'inbox'
    loaded, warning = Settings.load(tmp_path / '.jotline-settings.json')
    assert not warning and loaded.saved_views['review']['query'] == '#work -blocked'


async def test_bulk_keyboard_merge_and_failures(tmp_path):
    vault = Vault(tmp_path)
    one, two = saved(vault, 'one'), saved(vault, 'two')
    app = Jotline(vault)
    async with app.run_test() as pilot:
        app.select_bulk()
        await pilot.pause()
        assert isinstance(app.screen, SelectNotes)
        await pilot.press('space', 'down', 'space')
        assert len(app.screen.query_one(SelectionList).selected) == 2
        await pilot.press('ctrl+s')
        await pilot.pause()
        await pilot.press(*'merge', 'enter')
        assert app.current.body in ('one\n\n---\n\ntwo', 'two\n\n---\n\none')
        assert vault.read(one.id).body == 'one' and vault.read(two.id).body == 'two'
        app.run_bulk([one.id, 'missing'], 'archive')
        assert vault.read(one.id).collection == 'archive'
        app.run_bulk([two.id], 'tag', 'work')
        assert vault.read(two.id).tags == {'work'}


def test_actions_append_then_archive_and_failure(tmp_path):
    vault = Vault(tmp_path)
    source, target = saved(vault, 'source'), saved(vault, 'target\n')
    steps = [{'type': 'uppercase'}, {'type': 'append', 'value': target.id}, {'type': 'archive'}]
    result = run_action(vault, source, steps)
    assert result.collection == 'archive' and vault.read(target.id).body == 'target\nSOURCE'
    source = saved(vault, 'keep')
    with pytest.raises(OSError):
        run_action(vault, source, [{'type': 'append', 'value': 'missing'}, {'type': 'archive'}])
    assert vault.read(source.id).collection == 'inbox'
    with pytest.raises(ValueError):
        run_action(vault, source, [{'type': 'append', 'value': source.id}])
    output = []
    run_action(vault, source, [{'type': 'export'}], export=output.append)
    assert output == ['keep']


@pytest.mark.parametrize('newline', ['\n', '\r\n', '\r'])
def test_cli_updates_json_and_actions(tmp_path, newline):
    vault = Vault(tmp_path)
    note = saved(vault, 'middle')
    def cli(*args, input=None):
        return subprocess.run([sys.executable, '-m', 'jotline', '--vault', str(tmp_path), *args],
                              # Binary pipes prevent Windows text mode from
                              # translating the fixture before Jotline reads it.
                              input=input.encode('utf-8') if input is not None else None,
                              capture_output=True, timeout=15)
    assert cli('append', note.id, input=newline + 'end').returncode == 0
    assert cli('prepend', note.id, input='start' + newline).returncode == 0
    expected = f'start{newline}middle{newline}end'
    assert vault.read(note.id).body == expected
    result = cli('list', '--json')
    assert json.loads(result.stdout)[0]['id'] == note.id
    other = saved(vault, 'private', 'other')
    assert cli('append', other.id, 'bad').returncode == 1
    assert vault.read(other.id).body == 'private'
    Settings(actions={'shout': [{'type': 'uppercase'}, {'type': 'export'}]}).save(tmp_path / '.jotline-settings.json')
    result = cli('run', 'shout', note.id)
    assert result.returncode == 0 and result.stdout == expected.upper().encode('utf-8')


@pytest.mark.parametrize('settings', [Settings(actions={'bad': [{'type': 'shell'}]}),
                                     Settings(saved_views={'bad': {}})])
def test_invalid_workflow_configuration_rejected(settings):
    with pytest.raises(ValueError):
        settings.validate()


async def test_autocomplete_link_and_snippet_cancel(tmp_path):
    vault = Vault(tmp_path)
    note = saved(vault, '# Linked')
    Templates(tmp_path).save('snippet', 'expanded')
    app = Jotline(vault)
    async with app.run_test() as pilot:
        editor = app.query_one('#editor', TextArea)

        async def type_trigger(trigger: str) -> None:
            """Put [[ or ;; at the cursor, then open the same completion palette as editing."""
            editor.focus()
            await pilot.pause()
            editor.move_cursor(editor.document.end)
            await pilot.pause()
            assert editor.selection.is_empty
            editor.insert(trigger)
            await pilot.pause()
            if not isinstance(app.screen, Palette):
                # macos-latest Pilot can drop TextArea.Changed after a palette
                # round-trip, and the editor may not have focus yet. Insert the
                # trigger, collapse any leftover selection, and call the same
                # hook the editor uses after a real change.
                editor.focus()
                editor.move_cursor(editor.document.end)
                await pilot.pause()
                offset = editor.char_offset(editor.cursor_location, editor.text)
                assert editor.text[max(0, offset - 2):offset] == trigger
                assert editor.selection.is_empty
                app.offer_completion()
            await wait_for_command_palette(app, pilot)

        await type_trigger('[[')
        await pilot.press('enter')
        await pilot.pause()
        assert editor.text == f'[[{note.id}|Linked]]'
        editor.focus()
        await pilot.pause()
        editor.move_cursor(editor.document.end)
        editor.insert(' ')
        await type_trigger(';;')
        await pilot.press(*'snippet', 'enter')
        await pilot.pause()
        assert editor.text.endswith(' expanded')
        await type_trigger(';;')
        await pilot.press('escape')
        assert editor.text.endswith('expanded;;')


async def test_offer_completion_without_editor_focus(tmp_path):
    Templates(tmp_path).save('snippet', 'expanded')
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        editor = app.query_one('#editor', TextArea)
        app.query_one('#search', Input).focus()
        await pilot.pause()
        assert not editor.has_focus
        editor.insert(';;')
        await pilot.pause()
        if not isinstance(app.screen, Palette):
            app.offer_completion()
        await wait_for_command_palette(app, pilot)
        await pilot.press('escape')
        assert editor.text.endswith(';;')


async def test_local_action_text_transform_undo_and_initial_note(tmp_path):
    vault = Vault(tmp_path)
    note = saved(vault, 'lower')
    Settings(actions={'shout': [{'type': 'uppercase'}]}, startup='daily').save(tmp_path / '.jotline-settings.json')
    app = Jotline(vault, initial_note=note)
    async with app.run_test() as pilot:
        assert app.current.id == note.id
        app.run_local_action('shout')
        assert app.query_one('#editor', TextArea).text == 'LOWER'
        await pilot.press('ctrl+z')
        assert app.query_one('#editor', TextArea).text == 'lower'
        assert app.save_current()
        assert vault.read(note.id).body == 'lower'


async def test_settings_defaults_keep_views_and_actions(tmp_path):
    from textual.widgets import Button
    settings = Settings(actions={'shout': [{'type': 'uppercase'}]}, saved_views={
        'review': dict(workspace='default', query='#work', collection='all', sort='title', theme='nord')})
    settings.save(tmp_path / '.jotline-settings.json')
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        await pilot.press('f1')
        app.screen.query_one('#default-preferences', Button).press()
        await pilot.pause()
        await pilot.press('ctrl+s')
        assert app.settings.actions == settings.actions
        assert app.settings.saved_views == settings.saved_views


def test_oversized_action_settings_leave_previous_file(tmp_path):
    path = tmp_path / '.jotline-settings.json'
    settings = Settings()
    settings.save(path)
    before = path.read_bytes()
    settings.actions = {'large': [{'type': 'template', 'value': 'x' * (256 * 1024)}]}
    with pytest.raises(ValueError, match='size limit'):
        settings.save(path)
    assert path.read_bytes() == before


async def test_replace_all_rejects_oversized_output_before_editing(tmp_path, monkeypatch):
    import jotline.app as module
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        editor = app.query_one('#editor', TextArea)
        editor.insert('aaaa')
        app.command('find')
        await pilot.pause()
        app.screen.query_one('#find-query', Input).value = 'a'
        app.screen.query_one('#replace-value', Input).value = 'long'
        monkeypatch.setattr('jotline.screens.EDIT_LIMIT_BYTES', 4)
        app.screen.replace_matches(all_matches=True)
        assert editor.text == 'aaaa'
