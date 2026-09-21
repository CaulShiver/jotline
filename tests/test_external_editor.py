"""Handing a note out to $EDITOR and taking it back."""
from contextlib import nullcontext

from jotline.app import Jotline
from jotline.external_editor import EDITOR_VARIABLES, configured_editor
from jotline.store import Vault


def test_the_first_set_variable_wins():
    assert configured_editor({'JOTLINE_EDITOR': 'hx', 'VISUAL': 'vi', 'EDITOR': 'nano'}) == ['hx']
    assert configured_editor({'VISUAL': 'vi', 'EDITOR': 'nano'}) == ['vi']
    assert configured_editor({'EDITOR': 'nano'}) == ['nano']
    assert EDITOR_VARIABLES == ('JOTLINE_EDITOR', 'VISUAL', 'EDITOR')


def test_arguments_in_the_variable_are_kept():
    assert configured_editor({'EDITOR': 'code --wait'}) == ['code', '--wait']
    assert configured_editor({'EDITOR': '"my editor" --wait'}) == ['my editor', '--wait']


def test_an_unusable_value_reads_as_no_editor():
    assert configured_editor({}) == []
    assert configured_editor({'EDITOR': '   '}) == []
    assert configured_editor({'EDITOR': 'broken "quote'}) == []
    # An unusable first choice falls through rather than blocking the rest.
    assert configured_editor({'VISUAL': 'broken "quote', 'EDITOR': 'vi'}) == ['vi']


async def test_an_external_edit_is_read_back_into_the_editor(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    app = Jotline(vault)
    monkeypatch.setenv('EDITOR', 'stub-editor')
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.press(*'first draft')
        await pilot.pause()

        def edit(command, path):
            path.write_text(path.read_text().replace('first draft', 'rewritten outside'))
            return ''

        monkeypatch.setattr(Jotline, 'hand_to_editor', lambda self, c, p: edit(c, p))
        app.action_external_editor()
        await pilot.pause()
        assert app.current.body == 'rewritten outside'
        assert app.editor().text == 'rewritten outside'
        assert not app.dirty


async def test_an_unset_editor_says_so_and_changes_nothing(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    app = Jotline(vault)
    for name in EDITOR_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    called = []
    monkeypatch.setattr(Jotline, 'hand_to_editor', lambda self, c, p: called.append(c) or '')
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.press(*'draft')
        await pilot.pause()
        app.action_external_editor()
        await pilot.pause()
        assert called == []
        assert app.editor().text == 'draft'


async def test_an_encrypted_note_is_never_handed_out(tmp_path, monkeypatch):
    """Its file holds sealed text; an editor would save ciphertext back."""
    vault = Vault(tmp_path)
    app = Jotline(vault)
    monkeypatch.setenv('EDITOR', 'stub-editor')
    called = []
    monkeypatch.setattr(Jotline, 'hand_to_editor', lambda self, c, p: called.append(c) or '')
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.press(*'secret')
        await pilot.pause()
        app.current.encrypted = True
        app.action_external_editor()
        await pilot.pause()
        assert called == []


async def test_a_deleted_file_reports_rather_than_reloading_nothing(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    app = Jotline(vault)
    monkeypatch.setenv('EDITOR', 'stub-editor')
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.press(*'draft')
        await pilot.pause()
        note_id = app.current.id
        monkeypatch.setattr(Jotline, 'hand_to_editor',
                            lambda self, c, p: (tmp_path / f'{note_id}.md').unlink() or '')
        app.action_external_editor()
        await pilot.pause()
        # The on-screen draft survives a note that went missing out there.
        assert app.editor().text == 'draft'


async def test_a_corrupted_header_reports_rather_than_loading_it(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    app = Jotline(vault)
    monkeypatch.setenv('EDITOR', 'stub-editor')
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.press(*'draft')
        await pilot.pause()
        note_id = app.current.id
        monkeypatch.setattr(Jotline, 'hand_to_editor',
                            lambda self, c, p: (tmp_path / f'{note_id}.md').write_text('no header at all') or '')
        app.action_external_editor()
        await pilot.pause()
        assert app.editor().text == 'draft'


async def test_an_editor_that_will_not_start_is_reported(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    app = Jotline(vault)
    monkeypatch.setenv('EDITOR', 'no-such-editor-anywhere')

    def missing(*args, **kwargs):
        raise OSError('No such file or directory')

    # Suspending is the terminal's business; the run that fails is the point.
    monkeypatch.setattr(Jotline, 'suspend', lambda self: nullcontext())
    monkeypatch.setattr('jotline.app.subprocess.run', missing)
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.press(*'draft')
        await pilot.pause()
        assert 'did not start' in app.hand_to_editor(['no-such-editor-anywhere'], tmp_path / 'x.md')
        app.action_external_editor()
        await pilot.pause()
        assert app.editor().text == 'draft'


async def test_a_terminal_that_cannot_suspend_says_so(tmp_path, monkeypatch):
    """Headless is a real way to run this, and it must not look like a no-op."""
    vault = Vault(tmp_path)
    app = Jotline(vault)
    monkeypatch.setenv('EDITOR', 'stub-editor')
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.press(*'draft')
        await pilot.pause()
        problem = app.hand_to_editor(['stub-editor'], tmp_path / 'x.md')
        assert 'cannot hand itself' in problem
        app.action_external_editor()
        await pilot.pause()
        assert app.editor().text == 'draft'
