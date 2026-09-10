from datetime import date
import subprocess
import sys

import pytest
from textual.widgets import Input, OptionList, TextArea

from jotline.app import Jotline, Palette, TextPrompt
from jotline.settings import Settings
from jotline.store import Vault, tagged_body


def test_legacy_notes_and_workspace_roundtrip(tmp_path):
    (tmp_path / 'legacy.md').write_text('# Existing #Work')
    vault = Vault(tmp_path)
    assert vault.read('legacy').workspace == 'default'
    work = vault.new('# Work #work #plan', workspace='work')
    vault.save(work)
    assert vault.read(work.id).workspace == 'work'
    assert {n.id for n in vault.search(workspace='default')} == {'legacy'}
    assert [n.id for n in vault.search('#work', workspace='work')] == [work.id]
    assert vault.tags('work') == {'work': 1, 'plan': 1}
    assert vault.workspaces() == {'default', 'work'}
    linked = vault.new(f'[[{work.id}]]', workspace='default')
    vault.save(linked)
    assert not vault.backlinks(work)
    linked.workspace = 'work'
    vault.save(linked)
    assert [n.id for n in vault.backlinks(work)] == [linked.id]


def test_daily_logs_and_recovery_stay_in_workspace(tmp_path):
    vault = Vault(tmp_path)
    first = vault.append_daily('private')
    second = vault.append_daily('meeting', workspace='work')
    assert first.id == f'daily-{date.today()}'
    assert second.id != first.id
    assert vault.daily(workspace='work').body.endswith('meeting\n')
    assert 'private' not in second.body
    assert vault.recovery(second).workspace == 'work'


@pytest.mark.parametrize('name', ['../outside', '', 'Work', 'x\n', 'a' * 49, [], None])
def test_invalid_workspace_is_rejected(tmp_path, name):
    vault = Vault(tmp_path)
    with pytest.raises(ValueError):
        vault.new(workspace=name)
    note = vault.new('safe')
    vault.save(note)
    note.workspace = name
    with pytest.raises(ValueError):
        vault.save(note)
    assert vault.read(note.id).workspace == 'default'
    with pytest.raises(ValueError):
        Settings(workspace_names=[name]).validate()


def test_tag_addition_deduplicates_without_rewriting_body():
    body = '# Title\r\nText #Work\n'
    assert tagged_body(body, '#WORK ideas project/topic') == body + '\n\n#ideas #project/topic'
    assert tagged_body(body, 'work') == body
    for invalid in ('##tag', 'bad!', '#', ''):
        with pytest.raises(ValueError):
            tagged_body(body, invalid)


async def test_create_switch_tag_browse_move_and_reopen(tmp_path):
    vault = Vault(tmp_path)
    app = Jotline(vault)
    async with app.run_test(size=(110, 40)) as pilot:
        app.query_one('#editor', TextArea).insert('Personal note')
        await pilot.press('ctrl+w')
        assert isinstance(app.screen, Palette)
        app.screen.query_one(Input).value = 'Create'
        await pilot.press('enter')
        await pilot.pause()
        assert isinstance(app.screen, TextPrompt)
        app.screen.query_one(Input).value = 'work'
        await pilot.press('enter')
        await pilot.pause()
        assert app.workspace == 'work'
        assert [n.body for n in vault.search(workspace='default')] == ['Personal note']
        assert app.query_one('#notes', OptionList).option_count == 0
        app.query_one('#editor', TextArea).insert('Meeting')
        app.command('add-tags')
        await pilot.pause()
        app.screen.query_one(Input).value = '#planning #team'
        await pilot.press('enter')
        await pilot.pause()
        note_id = app.current.id
        assert vault.read(note_id).tags == {'planning', 'team'}
        await pilot.press('ctrl+t')
        await pilot.pause()
        assert isinstance(app.screen, Palette)
        app.screen.query_one(Input).value = 'planning'
        await pilot.press('enter')
        await pilot.pause()
        assert app.query_one('#search', Input).value == '#planning'
        assert app.query_one('#notes', OptionList).option_count == 1
        app.move_workspace('default')
        assert vault.read(note_id).workspace == 'default'
        assert app.query_one('#notes', OptionList).option_count == 0
        app.command('settings')
        await pilot.pause()
        await pilot.click('#default-preferences')
        await pilot.press('ctrl+s')
        await pilot.pause()
        assert app.settings.active_workspace == 'work'
    assert Jotline(vault).workspace == 'work'


async def test_switch_save_conflict_preserves_workspace_and_buffer(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('original')
    vault.save(note)
    app = Jotline(vault)
    async with app.run_test() as pilot:
        app.load_id(note.id)
        other = vault.read(note.id)
        other.body = 'external'
        vault.save(other)
        app.query_one('#editor', TextArea).load_text('unsaved')
        app.switch_workspace('work')
        assert app.workspace == 'default'
        assert app.query_one('#editor', TextArea).text == 'unsaved'
        assert not app.settings_path.exists()
        assert vault.read(note.id).body == 'external'


def test_cli_workspace_capture_tags_and_daily(tmp_path):
    def cli(*args, check=True):
        return subprocess.run([sys.executable, '-m', 'jotline', '--vault', str(tmp_path), *args],
                              text=True, capture_output=True, check=check)
    personal = cli('capture', 'Personal #home').stdout.strip()
    work = cli('--workspace', 'work', 'capture', 'Meeting').stdout.strip()
    cli('--workspace', 'work', 'tag', work, '#team', 'plan')
    assert '#team\t1' in cli('--workspace', 'work', 'tags').stdout
    assert work not in cli('list').stdout
    assert personal not in cli('--workspace', 'work', 'list').stdout
    assert cli('export', work, check=False).returncode == 1
    assert 'work' in cli('workspaces').stdout
    assert cli('capture', '--daily', 'personal').stdout != cli('--workspace', 'work', 'capture', '--daily', 'work').stdout
