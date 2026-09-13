import json

import pytest
from textual.app import App
from textual.widgets import Input, Select, TextArea

from jotline.actions import preview_action
from jotline.action_history import ActionHistory, run_recorded_action
from jotline.action_recipes import merge_recipes, read_recipes, write_recipes
from jotline.action_ui import ActionEditor, ActionReport
from jotline.store import Vault


def saved(vault, body):
    note = vault.new(body)
    vault.save(note)
    return note


def test_preview_has_no_note_or_clipboard_side_effects(tmp_path):
    vault = Vault(tmp_path)
    source, target = saved(vault, ' source '), saved(vault, 'target')
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    result, effects = preview_action(vault, source, [
        {'type': 'strip'}, {'type': 'uppercase'}, {'type': 'append', 'value': target.id},
        {'type': 'copy'}, {'type': 'export'}, {'type': 'archive'}])
    assert result.body == 'SOURCE' and result.collection == 'archive'
    assert len(effects) == 4
    assert source.body == ' source '
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}


def test_history_reports_partial_effects_without_body(tmp_path):
    vault = Vault(tmp_path)
    source, target = saved(vault, 'very private text'), saved(vault, 'target')
    with pytest.raises(OSError):
        run_recorded_action(vault, source, [
            {'type': 'append', 'value': target.id}, {'type': 'append', 'value': 'missing'},
            {'type': 'archive'}], name='process')
    record = ActionHistory(tmp_path).read()[0]
    assert record['status'] == 'failed'
    assert [step['status'] for step in record['steps']] == ['completed', 'failed', 'not-run']
    assert 'very private text' not in (tmp_path / '.jotline-action-history.json').read_text()
    assert vault.read(source.id).collection == 'inbox'
    assert vault.read(target.id).body.endswith('very private text')


def test_history_final_save_failure_is_distinct(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    source = saved(vault, 'source')
    def failure(note):
        raise OSError('disk full')
    monkeypatch.setattr(vault, 'save', failure)
    with pytest.raises(OSError):
        run_recorded_action(vault, source, [{'type': 'uppercase'}])
    assert ActionHistory(tmp_path).read()[0]['steps'] == [
        {'type': 'uppercase', 'status': 'completed'}, {'type': 'save', 'status': 'failed'}]


def test_history_bounded_and_logging_failure_does_not_hide_success(tmp_path):
    vault = Vault(tmp_path)
    note = saved(vault, 'source')
    history = ActionHistory(tmp_path)
    for index in range(105):
        history.append({'name': str(index), 'steps': []})
    assert len(history.read()) == 100 and history.read()[0]['name'] == '5'
    (tmp_path / '.jotline-action-history.json').write_text('invalid')
    warnings = []
    result = run_recorded_action(vault, note, [{'type': 'uppercase'}], history_warning=warnings.append)
    assert result.body == 'SOURCE' and warnings


def test_recipe_roundtrip_collision_and_link_rejection(tmp_path):
    path = tmp_path / 'recipes.json'
    actions = {'shout': [{'type': 'uppercase'}, {'type': 'copy'}]}
    write_recipes(path, actions)
    assert read_recipes(path) == actions
    with pytest.raises(FileExistsError):
        write_recipes(path, actions)
    with pytest.raises(ValueError, match='already exist'):
        merge_recipes(actions, actions)
    link = tmp_path / 'link.json'
    try:
        link.symlink_to(path)
    except (OSError, NotImplementedError):
        pytest.skip('symlinks unavailable')
    with pytest.raises(OSError):
        read_recipes(link)
    assert read_recipes(path) == actions


@pytest.mark.parametrize('payload', [
    {'format': 'jotline-actions', 'version': 1, 'actions': {'bad': [{'type': 'shell'}]}},
    {'format': 'jotline-actions', 'version': True, 'actions': {}},
])
def test_import_rejects_unsupported_recipes(tmp_path, payload):
    path = tmp_path / 'invalid.json'
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        read_recipes(path)


@pytest.mark.asyncio
async def test_builder_create_preview_save_and_narrow_escape(tmp_path):
    vault = Vault(tmp_path)
    note = saved(vault, 'hello')
    app = App()
    results = []
    async with app.run_test(size=(60, 20)) as pilot:
        app.push_screen(ActionEditor(vault, note), results.append)
        await pilot.pause()
        editor = app.screen
        editor.query_one('#recipe-name', Input).value = 'shout'
        editor.query_one('#step-type', Select).value = 'uppercase'
        editor.action_save()
        await pilot.pause()
        assert results == [('shout', [{'type': 'uppercase'}])]
        assert vault.read(note.id).body == 'hello'
        app.push_screen(ActionReport('Preview', 'hello'))
        await pilot.pause()
        await pilot.press('escape')
        assert not isinstance(app.screen, ActionReport)
        app.push_screen(ActionEditor(vault, note), results.append)
        await pilot.pause()
        await pilot.press('escape')
        assert results[-1] is None


def test_copy_and_create_starters_preserve_source(tmp_path):
    from jotline.actions import BUILTIN_ACTIONS, run_action
    vault = Vault(tmp_path)
    source = saved(vault, ' original source ')
    copies, exports = [], []
    for name in ('copy-clean-text', 'copy-markdown-quote', 'create-from-template'):
        result = run_action(vault, source, BUILTIN_ACTIONS[name], copy=copies.append, export=exports.append)
        assert result.body == source.body == vault.read(source.id).body
    assert copies == ['original source', '>  original source ']
    assert exports[0].startswith('# Meeting')


@pytest.mark.asyncio
async def test_builder_picks_target_by_title_and_previews_without_writes(tmp_path):
    from jotline.app import Palette
    vault = Vault(tmp_path)
    note, target = saved(vault, 'source'), saved(vault, '# My project')
    app = App()
    async with app.run_test(size=(80, 40)) as pilot:
        app.push_screen(ActionEditor(vault, note, name='process', steps=[{'type': 'append', 'value': 'choose-target'}]))
        await pilot.pause()
        editor = app.screen
        editor.query_one('#step-target').press()
        await pilot.pause()
        assert isinstance(app.screen, Palette)
        app.screen.dismiss(target.id)
        await pilot.pause()
        assert editor.query_one('#step-value', TextArea).text == target.id
        editor.query_one('#recipe-preview').press()
        await pilot.pause()
        assert isinstance(app.screen, ActionReport)
        assert 'source' in app.screen.query_one(TextArea).text
        assert vault.read(target.id).body == '# My project'
        await pilot.press('escape')
        editor.action_save()
        await pilot.pause()
        assert not isinstance(app.screen, ActionEditor)


def test_action_post_commit_failure_carries_saved_note(tmp_path, monkeypatch):
    from jotline.actions import ActionCommitError
    from jotline.filesystem import fs
    vault = Vault(tmp_path)
    source = saved(vault, 'source')
    real_save = vault.save
    original_fsync = fs.fsync
    def save_then_fail_after_replacement(working):
        # Inject specifically at the durability call after Vault updates its
        # committed baseline; earlier snapshots/fsyncs must still succeed.
        def fail_committed(fd):
            if working.original != source.original:
                raise OSError('injected directory fsync failure')
            return original_fsync(fd)
        with monkeypatch.context() as context:
            context.setattr(fs, 'fsync', fail_committed)
            real_save(working)
    monkeypatch.setattr(vault, 'save', save_then_fail_after_replacement)
    with pytest.raises(ActionCommitError, match='was saved') as caught:
        run_recorded_action(vault, source, [{'type': 'uppercase'}])
    assert caught.value.note.body == vault.read(source.id).body == 'SOURCE'
    assert caught.value.note.original == vault.read(source.id).original
    assert source.body == 'source'
    record = ActionHistory(tmp_path).read()[0]
    assert record['status'] == 'committed-with-warning'
    assert record['steps'][-1] == {'type': 'save', 'status': 'committed-with-warning'}


@pytest.mark.parametrize('body,quoted', [
    ('first\n\nsecond\n', '> first\n> \n> second\n'),
    ('first\r\n\r\nsecond\r\n', '> first\r\n> \r\n> second\r\n'),
    ('first\r\rsecond\r', '> first\r> \r> second\r'),
    ('', '> '), ('\n', '> \n'), ('first\nlast', '> first\n> last'),
])
def test_quote_recipe_prefixes_every_line_and_preserves_endings(tmp_path, body, quoted):
    from jotline.actions import BUILTIN_ACTIONS, run_action
    vault = Vault(tmp_path)
    source = saved(vault, body)
    output = []
    result = run_action(vault, source, BUILTIN_ACTIONS['copy-markdown-quote'], copy=output.append)
    assert output == [quoted]
    assert result.body == vault.read(source.id).body == body
    _, effects = preview_action(vault, source, BUILTIN_ACTIONS['copy-markdown-quote'])
    assert quoted in effects[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('size', [(60, 20), (80, 24)])
async def test_builder_keyboard_only_preview_close_save(tmp_path, size):
    vault = Vault(tmp_path)
    source = saved(vault, 'one\n\ntwo')
    app = App()
    results = []
    async with app.run_test(size=size) as pilot:
        app.push_screen(ActionEditor(vault, source, steps=[{'type': 'strip'}, {'type': 'copy'}, {'type': 'restore'}]), results.append)
        await pilot.pause()
        await pilot.press(*list('quote-action'))
        # Traverse all controls using real keyboard focus, allowing the scroll
        # container to bring each off-screen control into view.
        seen = set()
        for _ in range(25):
            await pilot.press('tab')
            focused = app.focused
            seen.add(focused.id)
            if focused.id == 'step-type':
                await pilot.press('enter', 'down', 'enter')
                assert focused.value == 'quote'
            if focused.id == 'recipe-preview':
                break
        assert app.focused.id == 'recipe-preview', seen
        assert {'step-type', 'step-value', 'step-target', 'step-add'} <= seen
        region = app.focused.region
        assert 0 <= region.y < size[1] and region.bottom <= size[1]
        await pilot.press('enter')
        await pilot.pause()
        assert isinstance(app.screen, ActionReport)
        assert '> one\n> \n> two' in app.screen.query_one(TextArea).text
        await pilot.press('escape')
        await pilot.pause()
        assert isinstance(app.screen, ActionEditor)
        await pilot.press('tab')
        assert app.focused.id == 'recipe-save'
        await pilot.press('enter')
        await pilot.pause()
        assert results[0][0] == 'quote-action'
        assert results[0][1][0] == {'type': 'quote'}
        assert vault.read(source.id).body == source.body
