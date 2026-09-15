import json
import subprocess
import sys

import pytest

from textual.widgets import Markdown, Static, TextArea

from jotline.app import Jotline, Palette
from jotline.export import printable_markdown
from jotline.links import (
    connection_mark,
    iter_wiki_links,
    wiki_href,
    wiki_link_at,
    wiki_link_targets,
    wiki_target_from_href,
)
from jotline.screens import MarkdownPreview
from jotline.store import Vault


def test_wiki_links_ignore_fences_and_code_spans():
    body = (
        "# Hub\n\n"
        "See [[plain]] and [[target|label]]\n"
        "```\n[[fenced]]\n```\n"
        "Inline `[[span]]` stays code.\n"
    )
    assert wiki_link_targets(body)[0] == {"plain", "target"}
    links = list(iter_wiki_links(body))
    assert [link.target for link in links] == ["plain", "target"]
    assert links[0].snippet.startswith("See [[plain]]")
    assert printable_markdown(body, {"plain": "Plain"}) == (
        "# Hub\n\nSee Plain and label\n```\n[[fenced]]\n```\nInline `[[span]]` stays code.\n"
    )
    assert printable_markdown("See [[plain]]", {"plain": "Plain"}, followable=True) == (
        f"See [Plain]({wiki_href('plain')})"
    )


def test_wiki_href_round_trips_spaces():
    target = "Ghost idea"
    href = wiki_href(target)
    assert " " not in href
    assert wiki_target_from_href(href) == target
    assert wiki_target_from_href("https://example.com") is None


def test_connection_mark_covers_every_status():
    assert connection_mark("ok") == "→"
    assert connection_mark("ambiguous") == "?"
    assert connection_mark("broken") == "!"
    with pytest.raises(ValueError, match="unknown link status"):
        connection_mark("unlinked")


def test_connections_snippets_broken_and_ambiguous(tmp_path):
    vault = Vault(tmp_path)
    first = vault.new("# Idea\n\nDurable thought")
    vault.save(first)
    twin = vault.new("# Idea\n\nAnother with the same title")
    vault.save(twin)
    source = vault.new(f"# Source\n\nNext step is [[{first.id}|Idea]]\nAlso [[Missing]] and [[Idea]]")
    vault.save(source)

    incoming = vault.backlinks(first)
    assert [note.id for note in incoming] == [source.id]

    info = vault.connections(first)
    assert info.incoming[0].snippet.startswith("Next step is")
    assert info.outgoing == []

    outgoing = vault.connections(source).outgoing
    statuses = {(item.target, item.status) for item in outgoing}
    assert (first.id, "ok") in statuses
    assert ("Missing", "broken") in statuses
    assert ("Idea", "ambiguous") in statuses
    idea_matches = [item for item in outgoing if item.target == "Idea"]
    assert {item.note_id for item in idea_matches} == {first.id, twin.id}


def test_fenced_example_does_not_create_a_backlink(tmp_path):
    vault = Vault(tmp_path)
    target = vault.new("# Target")
    vault.save(target)
    docs = vault.new(f"# Docs\n\n```\n[[{target.id}]]\n```\n")
    vault.save(docs)
    assert docs.links == set()
    assert vault.backlinks(target) == []


def test_locked_note_keeps_incoming_and_hides_outgoing(tmp_path):
    vault = Vault(tmp_path)
    vault.setup_encryption("secret passphrase", n=2 ** 10)
    target = vault.new("# Private")
    target.encrypted = True
    vault.save(target)
    source = vault.new(f"# Pointer\n[[{target.id}|Private]]")
    vault.save(source)
    vault.lock()
    locked = vault.read(target.id)
    assert locked.locked
    info = vault.connections(locked)
    assert info.locked
    assert [item.note_id for item in info.incoming] == [source.id]
    assert info.outgoing == []


def test_cli_backlinks_text_and_json(tmp_path):
    def cli(*args):
        return subprocess.run(
            [sys.executable, "-m", "jotline", "--vault", str(tmp_path), *args],
            text=True, capture_output=True, check=True,
        )

    target = cli("capture", "Target note").stdout.strip()
    source = cli("capture", f"Source\n[[{target}|Target note]]").stdout.strip()
    text = cli("backlinks", target).stdout
    assert source in text and "←" in text
    payload = json.loads(cli("backlinks", target, "--json").stdout)
    assert payload["id"] == target
    assert payload["incoming"][0]["id"] == source
    assert "Target note" in payload["incoming"][0]["snippet"]
    missing = json.loads(cli("backlinks", source, "--json").stdout)
    assert missing["outgoing"][0]["status"] == "ok"


def test_cli_backlinks_does_not_create_a_vault(tmp_path):
    missing = tmp_path / "no-such-vault"
    result = subprocess.run(
        [sys.executable, "-m", "jotline", "--vault", str(missing), "backlinks", "last"],
        text=True, capture_output=True,
    )
    assert result.returncode != 0
    assert not missing.exists()


async def test_show_connections_and_cursor_follow(tmp_path):
    vault = Vault(tmp_path)
    target = vault.new("# Target")
    vault.save(target)
    source = vault.new(f"# Source\n\nSee [[{target.id}|Target]]\n")
    vault.save(source)
    app = Jotline(vault)
    async with app.run_test(size=(100, 35)) as pilot:
        app.load(source)
        await pilot.pause()
        bar = str(app.query_one("#connections", Static).render())
        assert "→ 1" in bar
        editor = app.query_one("#editor", TextArea)
        editor.move_cursor((2, 6))
        app.action_follow()
        await pilot.pause()
        assert app.current.id == target.id
        app.action_backlinks()
        await pilot.pause()
        assert isinstance(app.screen, Palette)
        assert any(key.startswith("open:") for key, _ in app.screen.choices)
        await pilot.press("enter")
        await pilot.pause()
        assert app.current.id == source.id


async def test_broken_link_creates_a_note_and_rewrites_to_a_stable_id(tmp_path):
    vault = Vault(tmp_path)
    app = Jotline(vault)
    async with app.run_test(size=(100, 35)) as pilot:
        editor = app.query_one("#editor", TextArea)
        editor.load_text("# Hub\n\nSee [[Ghost idea]]\n")
        await pilot.pause()
        app.connections()
        bar = str(app.query_one("#connections", Static).render())
        assert "broken" in bar
        editor.move_cursor((2, 8))
        app.action_follow()
        await pilot.pause()
        assert isinstance(app.screen, Palette)
        await pilot.press("enter")
        await pilot.pause()
        created = app.current
        assert created.title == "Ghost idea"
        assert vault.backlinks(created)
        source = next(note for note in vault.notes() if note.id != created.id)
        assert f"[[{created.id}|Ghost idea]]" in source.body
        assert "[[Ghost idea]]" not in source.body


async def test_connections_panel_opens_from_alt_k_on_compact_terminal(tmp_path):
    vault = Vault(tmp_path)
    target = vault.new("# Target")
    vault.save(target)
    source = vault.new(f"# Source\n[[{target.id}|Target]]")
    vault.save(source)
    app = Jotline(vault, initial_note=source)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.query_one("#connections", Static).has_class("hidden")
        status = str(app.query_one("#status", Static).render())
        assert "→1" in status or "→ 1" in status or "→1" in app.connection_counts()
        await pilot.press("alt+k")
        await pilot.pause()
        assert isinstance(app.screen, Palette)
        assert app.screen.heading == "Connections"


async def test_preview_wiki_link_opens_the_target_note(tmp_path):
    vault = Vault(tmp_path)
    target = vault.new("# Target")
    vault.save(target)
    source = vault.new(f"# Source\n\nSee [[{target.id}|Target]]\n")
    vault.save(source)
    app = Jotline(vault, initial_note=source)
    async with app.run_test(size=(100, 35)) as pilot:
        await pilot.pause()
        app.action_preview()
        await pilot.pause()
        assert isinstance(app.screen, MarkdownPreview)
        markdown = app.screen.query_one(Markdown)
        markdown.post_message(Markdown.LinkClicked(markdown, wiki_href(target.id)))
        await pilot.pause()
        assert app.current.id == target.id


def test_wiki_link_at_cursor():
    body = "See [[note-id|Title]] now"
    assert wiki_link_at(body, 0, 6).target == "note-id"
    assert wiki_link_at(body, 0, len("See [[note-id|Title]]")).target == "note-id"
    assert wiki_link_at(body, 0, 0) is None
