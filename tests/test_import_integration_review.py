"""Cross-feature checks from the independent import/recovery review."""
import json
import subprocess
import sys

import pytest
from textual.widgets import TextArea

from jotline.app import Jotline
from jotline.importing import apply_import, preview_import
from jotline.import_ui import ImportPreviewScreen
from jotline.recovery_ui import RecoveryScreen
from jotline.store import Vault


def test_cli_cannot_apply_when_preview_is_requested(tmp_path):
    source = tmp_path / 'source.md'
    source.write_text('Must not import')
    target = tmp_path / 'vault'
    result = subprocess.run([sys.executable, '-m', 'jotline', '--vault', str(target),
                             'import', str(source), '--preview', '--apply'],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert 'not allowed with argument' in result.stderr
    assert not target.exists()


@pytest.mark.parametrize('size', [(60, 20), (80, 24)])
@pytest.mark.parametrize('kind,target,expected', [('import', 'import-apply', True), ('import', 'import-cancel', False),
                                                  ('recovery', 'preserve-reload', 'preserve-reload'),
                                                  ('recovery', 'preserve', 'preserve'), ('recovery', 'cancel', None)])
async def test_import_recovery_keyboard_controls_fit_narrow_screen(tmp_path, size, kind, target, expected):
    vault = Vault(tmp_path / 'vault')
    app = Jotline(vault)
    source = tmp_path / 'source.md'
    source.write_text('Import body')
    async with app.run_test(size=size) as pilot:
        results = []
        screen = (ImportPreviewScreen(preview_import(vault, source)) if kind == 'import'
                  else RecoveryScreen('Local draft', 'External version'))
        await app.push_screen(screen, results.append)
        for _ in range(15):
            if getattr(app.focused, 'id', None) == target:
                break
            await pilot.press('tab')
        assert getattr(app.focused, 'id', None) == target
        await pilot.pause()
        assert app.focused.region.bottom <= size[1]
        assert app.focused.region.right <= size[0]
        await pilot.press('enter')
        assert results == [expected]
        assert not vault.notes()


def test_apply_uses_preview_bytes_after_source_change(tmp_path):
    vault = Vault(tmp_path / 'vault')
    source = tmp_path / 'source.md'
    source.write_text('Reviewed version')
    plan = preview_import(vault, source)
    source.write_text('Unreviewed edit')
    result = apply_import(vault, plan)
    assert vault.read(result.imported[0]).body == 'Reviewed version'
    assert source.read_text() == 'Unreviewed edit'


def test_import_does_not_replace_note_created_after_preview(tmp_path):
    vault = Vault(tmp_path / 'vault')
    source = tmp_path / 'source.draftsExport'
    source.write_text(json.dumps([{'content': 'Import body', 'uuid': 'eac5e703-c215-4c91-8c29-7cc55d4cfa51'}]))
    plan = preview_import(vault, source)
    competing = vault.new('Concurrent capture')
    competing.id = plan.items[0].note.id
    vault.save(competing)
    result = apply_import(vault, plan)
    assert result.skipped == 1 and not result.imported and not result.errors
    assert vault.read(competing.id).body == 'Concurrent capture'


def test_import_timestamp_remains_compatible_with_date_search(tmp_path):
    vault = Vault(tmp_path / 'vault')
    source = tmp_path / 'source.draftsExport'
    source.write_text(json.dumps([{'content': 'Imported January note',
                                  'created_at': '20200102T120000', 'modified_at': '20200102T120000'}]))
    plan = preview_import(vault, source)
    if not plan.ready:
        assert plan.warnings  # Rejecting noncanonical dates is also safe.
        return
    result = apply_import(vault, plan)
    assert len(result.imported) == 1
    assert len(vault.search('updated-before:2020-01-03')) == 1


async def test_recovery_external_disappears_after_preview_preserves_local(tmp_path):
    vault = Vault(tmp_path)
    original = vault.new('original')
    vault.save(original)
    app = Jotline(vault, initial_note=original)
    async with app.run_test(size=(90, 40)) as pilot:
        app.autosave_timer.stop()
        app.query_one('#editor', TextArea).load_text('local edit')
        app.show_recovery_dialog()
        await pilot.pause()
        vault.file(original.id).unlink()
        await pilot.click('#preserve-reload')
        await pilot.pause()
        assert app.current.id != original.id
        assert app.current.body == 'local edit'
        assert vault.read(app.current.id).body == 'local edit'
