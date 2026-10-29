"""Malformed backup metadata must not prevent current notes from saving."""
from datetime import date
import zipfile

from jotline import history
from jotline.store import Vault


def test_deeply_nested_daily_manifest_is_quarantined_without_blocking_save(tmp_path):
    vault = Vault(tmp_path)
    folder = tmp_path / ".jotline-backups"
    folder.mkdir()
    daily = folder / f"daily-{date.today().isoformat()}.zip"
    with zipfile.ZipFile(daily, "w") as archive:
        archive.writestr("existing.md", "Previously backed up text")
        archive.writestr("jotline-backup-manifest.json", "[" * 2000 + "0" + "]" * 2000)

    note = vault.new("Current draft must still save")
    vault.save(note)

    assert vault.read(note.id).body == note.body
    assert history.validate_backup(daily) == (True, "")
    quarantined = list(folder.glob(".invalid-*.zip"))
    assert len(quarantined) == 1
    assert history.validate_backup(quarantined[0])[0] is False
    assert "Invalid daily backup retained" in vault.backup_warning
