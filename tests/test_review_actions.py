from jotline.app import Jotline
from jotline.settings import Settings
from jotline.store import Vault


async def test_action_transforms_whole_note_in_outliner(tmp_path):
    Settings(actions={'upper': [{'type': 'uppercase'}]}).save(tmp_path / '.jotline-settings.json')
    vault = Vault(tmp_path)
    note = vault.new('- one\n- two')
    vault.save(note)
    app = Jotline(vault, initial_note=note)
    async with app.run_test(size=(100,32)) as pilot:
        app.action_outliner()
        await pilot.pause()
        app.run_local_action('upper')
        await pilot.pause()
        app.save_current()
        assert app.editor().text == '- ONE\n- TWO'
        assert vault.read(note.id).body == '- ONE\n- TWO'
