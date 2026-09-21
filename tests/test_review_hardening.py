"""Regressions from the merged-main review, using synthetic local data."""
import errno
import os
from time import perf_counter

import pytest
from textual.widgets import TextArea

from jotline import export, filesystem, store
from jotline.app import Jotline
from jotline.crypto import EncryptionError, KeyFile
from jotline.markdown_editor import HIGHLIGHT_MAX_LINE_CHARS, highlight_line
from jotline.tasks import code_spans


def refuse_links(*args, **kwargs):
    raise OSError(errno.EOPNOTSUPP, 'hard links unavailable')


@pytest.mark.parametrize('existing', [False, True])
def test_native_exclusive_rename(tmp_path, existing):
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.write_bytes(b'complete content')
    if existing:
        target.write_bytes(b'other writer')
        with pytest.raises(FileExistsError):
            filesystem.rename_noreplace(source, target)
        assert source.read_bytes() == b'complete content'
        assert target.read_bytes() == b'other writer'
    else:
        filesystem.rename_noreplace(source, target)
        assert target.read_bytes() == b'complete content'
        assert not source.exists()


def test_export_refuses_concurrent_creator_without_hardlinks(tmp_path, monkeypatch):
    target = tmp_path / 'export.md'
    native = export.rename_noreplace

    def race(source, destination):
        target.write_bytes(b'other writer')
        return native(source, destination)

    monkeypatch.setattr(export.os, 'link', refuse_links)
    monkeypatch.setattr(export, 'rename_noreplace', race)
    with pytest.raises(export.ExportError, match='already exists'):
        export.write_export(target, b'our export')
    assert target.read_bytes() == b'other writer'
    assert list(tmp_path.iterdir()) == [target]


def test_export_without_hardlinks_still_publishes_complete_file(tmp_path, monkeypatch):
    monkeypatch.setattr(export.os, 'link', refuse_links)
    target = tmp_path / 'export.md'
    export.write_export(target, b'complete export')
    assert target.read_bytes() == b'complete export'
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize('existing_note', [False, True])
def test_note_publication_refuses_concurrent_creator_without_hardlinks(tmp_path, monkeypatch, existing_note):
    vault = store.Vault(tmp_path)
    note = vault.new('original')
    if existing_note:
        vault.save(note)
    baseline = note.original
    note.body = 'our replacement'
    native = filesystem.rename_noreplace

    def race(source, target, **kwargs):
        if target == note.id + '.md':
            vault.file(note.id).write_text('other writer', encoding='utf-8')
        return native(source, target, **kwargs)

    monkeypatch.setattr(store.os, 'link', refuse_links)
    monkeypatch.setattr(filesystem, 'rename_noreplace', race)
    with pytest.raises(OSError):
        vault.save(note)
    assert vault.file(note.id).read_text() == 'other writer'
    assert note.original == baseline and note.body == 'our replacement'
    if existing_note:
        displaced = list(tmp_path.glob('.jotline-displaced-*'))
        assert len(displaced) == 1 and displaced[0].read_text() == baseline


def test_key_publication_refuses_concurrent_key_without_hardlinks(tmp_path, monkeypatch):
    vault = store.Vault(tmp_path)
    native = filesystem.rename_noreplace
    key_path = tmp_path / '.jotline-key.json'

    def race(source, target, **kwargs):
        if target == key_path.name:
            key_path.write_text('existing wrapped key', encoding='utf-8')
        return native(source, target, **kwargs)

    monkeypatch.setattr(store.os, 'link', refuse_links)
    monkeypatch.setattr(filesystem, 'rename_noreplace', race)
    with vault.write_lock() as directory:
        key = KeyFile(b'x' * 16, 1024, 8, 1, b'x' * 12, b'x' * 48)
        with pytest.raises(FileExistsError):
            vault._write_key(directory, key, replace_existing=False)
    assert key_path.read_text() == 'existing wrapped key'


def test_unavailable_exclusive_publication_puts_the_original_back(tmp_path, monkeypatch):
    """Links refused and RENAME_NOREPLACE refused: sshfs, vboxsf, hgfs, some 9p.

    This used to leave the note under a hidden name that nothing lists, so the
    note disappeared from the app on its first overwrite -- deterministically,
    on every save. The restore falls back to a plain rename into a name this
    process observed free while holding the vault lock, so the note stays where
    the user can see it. The save still fails and the draft is still unsaved.
    """
    vault = store.Vault(tmp_path)
    note = vault.new('original')
    vault.save(note)
    baseline = note.original
    note.body = 'unsaved draft'
    monkeypatch.setattr(store.os, 'link', refuse_links)

    def unavailable(*args, **kwargs):
        raise OSError(errno.ENOTSUP, 'exclusive rename unavailable')

    monkeypatch.setattr(filesystem, 'rename_noreplace', unavailable)
    with pytest.raises(OSError, match='exclusive rename unavailable'):
        vault.save(note)
    assert note.body == 'unsaved draft' and note.original == baseline
    assert vault.file(note.id).read_text() == baseline
    assert list(tmp_path.glob('.jotline-displaced-*')) == []
    assert [found.id for found in store.Vault(tmp_path).notes()] == [note.id]


def test_restore_after_failed_save_does_not_overwrite_a_new_creator(tmp_path, monkeypatch):
    """The exclusive rename is still tried first, and still wins this race.

    Only a filesystem that refuses the flag outright falls back to a plain
    rename. A name taken by a concurrent creator raises EEXIST, which is not
    that, so the restore gives way and the original stays displaced.
    """
    vault = store.Vault(tmp_path)
    note = vault.new('original')
    vault.save(note)
    baseline = note.original
    note.body = 'unsaved draft'
    native = filesystem.rename_noreplace

    def fail_publication(*args, **kwargs):
        raise OSError(errno.EIO, 'publication failed')

    def race_restore(source, target, **kwargs):
        vault.file(note.id).write_text('late external writer', encoding='utf-8')
        return native(source, target, **kwargs)

    monkeypatch.setattr(store, 'publish_new', fail_publication)
    monkeypatch.setattr(filesystem, 'rename_noreplace', race_restore)
    with pytest.raises(OSError, match='publication failed'):
        vault.save(note)
    assert vault.file(note.id).read_text() == 'late external writer'
    displaced = list(tmp_path.glob('.jotline-displaced-*'))
    assert len(displaced) == 1 and displaced[0].read_text() == baseline
    assert note.original == baseline


@pytest.mark.skipif(os.name == 'nt', reason='POSIX directory rename while descriptor is open')
def test_exclusive_rename_uses_pinned_directory_after_path_swap(tmp_path):
    folder = tmp_path / 'folder'
    folder.mkdir()
    (folder / 'source').write_bytes(b'kept')
    fd = filesystem.fs.open(folder, filesystem.fs.O_RDONLY | filesystem.fs.O_DIRECTORY)
    try:
        moved = tmp_path / 'moved'
        folder.rename(moved)
        folder.mkdir()
        (folder / 'target').write_bytes(b'outside')
        filesystem.rename_noreplace('source', 'target', src_dir_fd=fd, dst_dir_fd=fd)
        assert (moved / 'target').read_bytes() == b'kept'
        assert (folder / 'target').read_bytes() == b'outside'
    finally:
        filesystem.fs.close(fd)


@pytest.mark.parametrize('end_column', [0, 3])
async def test_format_two_codeblocks_keeps_all_original_markers(tmp_path, end_column):
    body = '```python\na\n```\n\n```python\nb\n```'
    app = Jotline(store.Vault(tmp_path))
    async with app.run_test() as pilot:
        app.autosave_timer.stop()
        editor = app.query_one('#editor', TextArea)
        editor.load_text(body)
        editor.move_cursor((0, 0))
        editor.move_cursor((6, end_column), select=True)
        app.command('format:codeblock')
        await pilot.pause()
        assert editor.text.count('```python') == 2
        assert editor.text.startswith('````\n```python\n')
        await pilot.press('ctrl+z')
        assert editor.text == body


async def test_invalid_opener_is_wrapped_instead_of_unwrapped(tmp_path):
    body = '```a`b\ncontent\n```'
    app = Jotline(store.Vault(tmp_path))
    async with app.run_test() as pilot:
        editor = app.query_one('#editor', TextArea)
        editor.load_text(body)
        editor.move_cursor((0, 0))
        editor.move_cursor(editor.document.end, select=True)
        app.command('format:codeblock')
        await pilot.pause()
        assert editor.text == '````\n' + body + '\n````'


@pytest.mark.parametrize('text,expected', [
    ('`a` and ``b`c``', ['`a`', '``b`c``']),
    ('`` unmatched `[[x]]`', ['`[[x]]`']),
    ('`a\nb`', []),
    ('`` ``', ['`` ``']),
    ('`[[x]]` and [[x]]', ['`[[x]]`']),
])
def test_code_span_run_pairing(text, expected):
    assert [text[start:end] for start, end in code_spans(text)] == expected


def test_unmatched_inline_markdown_stays_responsive():
    # Old code took >3 seconds at just32k ticks; use100k plus output checks.
    text = 'x ' + '`' * 100_000 + ' [[x]]'
    started = perf_counter()
    assert list(code_spans(text)) == []
    assert export.printable_markdown(text, {'x': 'Target'}).endswith(' Target')
    assert highlight_line(text) == []
    assert highlight_line('**a ' * 16_000) == []
    assert perf_counter() - started < 1.0


def test_long_plain_fallback_and_unicode_offsets():
    assert highlight_line('é #tag ' * HIGHLIGHT_MAX_LINE_CHARS) == []
    line = 'é #tag ' * 40
    tags = [(start, end) for start, end, name in highlight_line(line) if name == 'md.tag']
    raw = line.encode('utf-8')
    assert len(tags) == 40
    assert all(raw[start:end] == b'#tag' for start, end in tags)


async def test_preview_bounds_total_table_work(tmp_path):
    app = Jotline(store.Vault(tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        editor = app.query_one('#editor', TextArea)
        table = '\n'.join(['| h | h |', '| - | - |'] + ['| a | b |'] * 150)
        assert len(table.encode()) < app.PREVIEW_MAX_BYTES
        assert len(table.splitlines()) < app.PREVIEW_MAX_BLOCKS
        assert not app.preview_fits(table)
        editor.load_text(table)
        app.command('live-preview')
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert 'Preview paused' in app._live_preview_text
        assert app.preview_fits('| h |\n| - |\n| a |')


@pytest.mark.parametrize('n,r,p', [(2**19, 15, 1), (2**20, 16, 4), (2**17, 12, 4)])
def test_scrypt_rejects_combined_cost_before_derivation(monkeypatch, n, r, p):
    from jotline import crypto
    key = KeyFile(b'x' * 16, n, r, p, b'x' * 12, b'x' * 48)
    monkeypatch.setattr(crypto.hashlib, 'scrypt', lambda *args, **kwargs: pytest.fail('KDF must not run'))
    with pytest.raises(EncryptionError, match='unsupported settings'):
        KeyFile.loads(key.dumps())
    with pytest.raises(EncryptionError, match='unsupported settings'):
        key.unwrap('passphrase')


def test_default_scrypt_settings_are_still_accepted():
    from jotline.crypto import SCRYPT_N, SCRYPT_R, SCRYPT_P
    key = KeyFile(b'x' * 16, SCRYPT_N, SCRYPT_R, SCRYPT_P, b'x' * 12, b'x' * 48)
    assert KeyFile.loads(key.dumps()) == key
