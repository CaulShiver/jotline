from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from jotline.filesystem import fs as os

import pytest

from jotline import templates as module
from jotline.templates import BUILTIN_TEMPLATES, Templates


def test_defaults_are_lazy_and_custom_templates_persist(tmp_path):
    templates = Templates(tmp_path)
    assert templates.names() == sorted(BUILTIN_TEMPLATES)
    assert not templates.path.exists()
    body = '# Résumé\r\n\r\n- [ ] Task\n'
    templates.save('my-template', body)
    assert (templates.path / 'my-template.md').read_bytes() == body.encode()
    assert Templates(tmp_path).read('my-template') == body
    assert 'my-template' in templates.names()
    if os.name != 'nt':
        assert (templates.path / 'my-template.md').stat().st_mode & 0o777 == 0o600
    assert not list(templates.path.glob('.tmp-*'))
    with pytest.raises(FileExistsError, match='^Template already exists; choose a different name$'):
        templates.save('my-template', 'replacement')
    assert templates.read('my-template') == body
    with pytest.raises(FileExistsError):
        templates.save('meeting', 'replacement')


def test_render_literal_placeholders_only(tmp_path, monkeypatch):
    class Clock:
        @staticmethod
        def now():
            return datetime(2026, 9, 10, 15, 42).astimezone()
    monkeypatch.setattr(module, 'datetime', Clock)
    templates = Templates(tmp_path)
    templates.save('literal', '{{date}} {{time}} {{workspace}} {{date}}\n{{unknown}} $(touch nope) `whoami` ${HOME}')
    assert templates.render('literal', 'work') == '2026-09-10 15:42 work 2026-09-10\n{{unknown}} $(touch nope) `whoami` ${HOME}'
    with pytest.raises(ValueError):
        templates.render('literal', '../other')
    assert not (tmp_path / 'nope').exists()


@pytest.mark.parametrize('name', ['../escape', '/tmp/escape', '', '.', 'UPPER', 'x' * 49, 'a/b', 'a.md'])
def test_invalid_names(tmp_path, name):
    templates = Templates(tmp_path)
    with pytest.raises(ValueError):
        templates.save(name, 'body')
    with pytest.raises(ValueError):
        templates.read(name)


def test_missing_and_bounded_utf8(tmp_path, monkeypatch):
    templates = Templates(tmp_path)
    with pytest.raises(FileNotFoundError):
        templates.read('missing')
    monkeypatch.setattr(module, 'MAX_NOTE_BYTES', 4)
    templates.save('fits', 'éé')
    with pytest.raises(ValueError):
        templates.save('large', 'ééé')
    (templates.path / 'large.md').write_bytes(b'12345')
    with pytest.raises(ValueError):
        templates.read('large')
    (templates.path / 'broken.md').write_bytes(b'\xff')
    with pytest.raises(UnicodeError):
        templates.read('broken')


def test_missing_template_reads_do_not_leak_vault_descriptors(tmp_path, resource_count):
    templates = Templates(tmp_path)
    before = resource_count()
    for _ in range(32):
        with pytest.raises(FileNotFoundError):
            templates.read('missing')
    assert resource_count() == before


def test_failed_template_creation_closes_owned_vault_handle(tmp_path, monkeypatch, resource_count):
    templates = Templates(tmp_path)
    before = resource_count()
    monkeypatch.setattr(os, 'mkdir',
                        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError('directory removed')))
    for _ in range(16):
        with pytest.raises(FileNotFoundError):
            with templates._directory(create=True):
                pytest.fail('creation should fail')
    assert resource_count() == before


@pytest.mark.parametrize('kind', ['symlink', 'file', 'fifo'])
def test_unsafe_template_directory(tmp_path, kind):
    templates = Templates(tmp_path)
    if kind == 'symlink':
        target = tmp_path / 'target'
        target.mkdir()
        templates.path.symlink_to(target, target_is_directory=True)
    elif kind == 'file':
        templates.path.write_text('not a directory')
    else:
        os.mkfifo(templates.path)
    with pytest.raises(OSError):
        templates.names()
    with pytest.raises(OSError):
        templates.read('custom')
    with pytest.raises(OSError):
        templates.save('custom', 'body')


@pytest.mark.parametrize('kind', ['symlink', 'directory', 'fifo'])
def test_unsafe_template_file(tmp_path, kind):
    templates = Templates(tmp_path)
    templates.path.mkdir()
    path = templates.path / 'unsafe.md'
    target = tmp_path / 'target'
    target.write_text('keep')
    if kind == 'symlink':
        path.symlink_to(target)
    elif kind == 'directory':
        path.mkdir()
    else:
        os.mkfifo(path)
    with pytest.raises(OSError):
        templates.read('unsafe')
    # One stray entry is skipped rather than hiding every other template.
    assert 'unsafe' not in templates.names()
    assert 'meeting' in templates.names()
    with pytest.raises(FileExistsError):
        templates.save('unsafe', 'body')
    assert target.read_text() == 'keep'
    assert not list(templates.path.glob('.tmp-*'))


def test_concurrent_save_has_one_winner(tmp_path):
    def save(body):
        try:
            Templates(tmp_path).save('same', body)
            return body
        except FileExistsError:
            return None
    bodies = ['first', 'second']
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save, bodies))
    winner, = [result for result in results if result is not None]
    assert Templates(tmp_path).read('same') == winner
    assert not list((tmp_path / '.jotline-templates').glob('.tmp-*'))
