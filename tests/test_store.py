import subprocess
import sys
from datetime import date, timedelta

import pytest
from jotline.store import ConflictError, Vault, daily_id, parse_calendar_date


def test_roundtrip_and_external_edit(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('# Café\n\nA thought #writing')
    vault.save(note)
    loaded = vault.read(note.id)
    assert loaded.body == note.body
    assert loaded.tags == {'writing'}
    loaded.body += '\nExternal edit'
    vault.save(loaded)
    note.body += '\nUnsaved thought'
    with pytest.raises(ConflictError):
        vault.save(note)
    assert vault.read(note.id).body == loaded.body
    recovered = vault.recovery(note)
    assert vault.read(recovered.id).body == note.body
    assert recovered.id != note.id


def test_search_trash_and_links(tmp_path):
    vault = Vault(tmp_path)
    first = vault.new('# Idea\n\nBlue sky #work')
    vault.save(first)
    second = vault.new(f'# Connected\n[[{first.id}|Idea]]')
    vault.save(second)
    assert [n.id for n in vault.search('blue #work')] == [first.id]
    assert not vault.search('#wor')
    assert [n.id for n in vault.backlinks(first)] == [second.id]
    first.body = '# Renamed\n'
    vault.save(first)
    assert len(vault.backlinks(first)) == 1
    first.collection = 'trash'
    vault.save(first)
    assert first.id not in [n.id for n in vault.search()]
    assert vault.search(collection='trash')[0].id == first.id
    first.collection = 'inbox'
    vault.save(first)
    assert len(vault.search()) == 2


def test_daily_and_corrupt_file(tmp_path):
    vault = Vault(tmp_path)
    first = vault.daily()
    vault.save(first)
    assert vault.daily().id == first.id
    (tmp_path / 'bad.md').write_text('---\njotline: 1\nstarred: not-json\n---\nkeep me')
    assert len(vault.notes()) == 1
    assert len(vault.warnings) == 1
    assert (tmp_path / 'bad.md').read_text().endswith('keep me')
    with pytest.raises(ValueError):
        vault.read('../escape')


def test_dated_daily_logs_are_per_day_and_workspace(tmp_path):
    vault = Vault(tmp_path)
    past = vault.daily(when=date(2026, 9, 1))
    assert past.id == "daily-2026-09-01"
    assert "# 2026-09-01" in past.body
    vault.save(past)
    assert vault.daily(when=date(2026, 9, 1)).body == past.body
    work = vault.daily(when=date(2026, 9, 1), workspace="work")
    assert work.id == "daily-2026-09-01-work"
    vault.save(work)
    appended = vault.append_daily("later", when=date(2026, 9, 1))
    assert appended.id == past.id
    assert appended.body.endswith("later\n")


def test_external_deletion_is_conflict(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('original')
    vault.save(note)
    vault.file(note.id).unlink()
    note.body = 'new writing'
    with pytest.raises(ConflictError):
        vault.save(note)


def test_cli_capture_export_and_daily(tmp_path):
    def cli(*args, input=None):
        return subprocess.run([sys.executable, '-m', 'jotline', '--vault', str(tmp_path), *args],
                              input=input, text=True, capture_output=True, check=True)
    note_id = cli('capture', input='hello\nworld\n').stdout.strip()
    assert cli('export', note_id).stdout == 'hello\nworld\n'
    assert 'hello' in cli('list', 'world').stdout
    first = cli('capture', '--daily', 'one').stdout.strip()
    second = cli('capture', '--daily', 'two').stdout.strip()
    assert first == second
    assert cli('export', first).stdout.endswith('one\n\ntwo\n')
    dated = cli('capture', '--daily', '--date', '2026-09-01', 'from the first').stdout.strip()
    assert dated == 'daily-2026-09-01'
    assert cli('export', dated).stdout.endswith('from the first\n')
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    assert cli('capture', '--daily', '--date', 'yesterday', 'later').stdout.strip() == f'daily-{yesterday}'


def test_parse_calendar_date_words_and_canonical_iso():
    today = date(2026, 9, 15)
    assert parse_calendar_date('today', today=today) == today
    assert parse_calendar_date('yesterday', today=today) == date(2026, 9, 14)
    assert parse_calendar_date('2026-09-01', today=today) == date(2026, 9, 1)
    assert daily_id(date(2026, 9, 1), 'work') == 'daily-2026-09-01-work'
    for value in ('20260901', '2026-9-1', 'tomorrow', '', '  '):
        with pytest.raises(ValueError):
            parse_calendar_date(value, today=today)


def test_wiki_link_strips_markup_characters(tmp_path):
    note = Vault(tmp_path).new('# Title | with [brackets]')
    assert note.wiki_link() == f'[[{note.id}|Title  with brackets]]'


@pytest.mark.parametrize("body", ["[" * 100_000, "[[x|" * 25_000], ids=['unclosed', 'repeated-alias'])
def test_malformed_wiki_links_finish_promptly(body):
    # Isolate the parser so a regression fails instead of hanging the suite.
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; from jotline.store import LINK; assert LINK.findall(sys.stdin.read()) == []"],
        input=body, text=True, capture_output=True, timeout=3,
    )
    assert result.returncode == 0, result.stderr


def test_link_grammar_and_multiple_search_terms(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new("# Mixed CASE\nBlue sky #work #ideas\n[[plain]] [[target|label]] [[other|]]")
    vault.save(note)
    assert note.links == {"plain", "target", "other"}
    assert [n.id for n in vault.search("BLUE sky #work #ideas")] == [note.id]
    assert not vault.search("blue #missing")
    assert not vault.search("blue absent")
    assert [n.id for n in vault.search(note.id)] == [note.id]


def test_read_workspace_guard_and_shared_titles(tmp_path):
    from jotline.store import OTHER_WORKSPACE

    vault = Vault(tmp_path)
    note = vault.new('# Work title', workspace='work')
    vault.save(note)
    assert vault.read(note.id, workspace='work').body == '# Work title'
    assert vault.titles('work') == {note.id: 'Work title'}
    assert vault.titles('default') == {}
    with pytest.raises(ValueError, match=OTHER_WORKSPACE):
        vault.read(note.id, workspace='default')
    with vault.locked() as directory:
        assert vault.read(note.id, workspace='work', directory=directory).id == note.id
        with pytest.raises(ValueError, match=OTHER_WORKSPACE):
            vault.read(note.id, workspace='default', directory=directory)
    assert vault.read(note.id).workspace == 'work'
