from pathlib import Path

from jotline.app import Jotline
from jotline.cli import build_parser
from jotline.navigation import Walkthrough
from jotline.recovery_ui import RecoveryScreen
from jotline.store import Vault
from jotline.sync import (
    GITIGNORE,
    RECOVERY_KEEP_BOTH,
    RECOVERY_KEEP_EDITING,
    RECOVERY_OPEN_COPY,
    git_recipe,
    sync_guide,
    syncthing_recipe,
)

from test_cli_scripting import run_cli


DOCS = Path(__file__).resolve().parents[1] / "docs" / "sync.md"


def test_cli_prints_git_syncthing_recovery_and_vault_path(tmp_path):
    result = run_cli(tmp_path, "sync")
    assert result.returncode == 0
    out = result.stdout.decode()
    resolved = str(tmp_path.resolve())
    assert resolved in out
    assert "not a Jotline cloud" in out
    assert "git init" in out
    assert "Syncthing" in out
    assert RECOVERY_KEEP_BOTH in out
    assert RECOVERY_OPEN_COPY in out
    assert RECOVERY_KEEP_EDITING in out
    assert ".jotline.lock" in out
    assert ".jotline-key.json" in out
    assert "jotline doctor" in out
    assert "jotline backup" in out


def test_cli_can_show_one_tool(tmp_path):
    git = run_cli(tmp_path, "sync", "git").stdout.decode()
    syncthing = run_cli(tmp_path, "sync", "syncthing").stdout.decode()
    assert "git init" in git and "## Syncthing" not in git
    assert "Share `" in syncthing and "## Git" not in syncthing
    assert RECOVERY_KEEP_BOTH in git and RECOVERY_KEEP_BOTH in syncthing


def test_sync_does_not_create_a_vault(tmp_path):
    missing = tmp_path / "no-such-vault"
    result = run_cli(missing, "sync")
    assert result.returncode == 0
    assert not missing.exists()


def test_docs_recipe_matches_in_app_text():
    docs = DOCS.read_text()
    for phrase in (RECOVERY_KEEP_BOTH, RECOVERY_OPEN_COPY, RECOVERY_KEEP_EDITING,
                   "jotline sync", "no Jotline cloud", ".jotline.lock", ".jotline-key.json"):
        assert phrase in docs
    assert GITIGNORE.strip() in docs
    guide = sync_guide(Path("/tmp/vault-example"))
    assert RECOVERY_KEEP_BOTH in git_recipe(Path("/tmp/x"))
    assert "Share `" in syncthing_recipe(Path("/tmp/x"))
    assert "Review external change" in guide


async def test_palette_opens_sync_recipe_walkthrough(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        app.command("sync-recipe")
        await pilot.pause()
        assert isinstance(app.screen, Walkthrough)
        assert "not a Jotline cloud" in app.screen.body
        assert RECOVERY_KEEP_BOTH in app.screen.body
        await pilot.press("escape")
        assert app.editor().has_focus


async def test_inbound_sync_uses_existing_recovery_dialog(tmp_path):
    """Git pull / Syncthing replacing a file is an external edit, not a Jotline cloud."""
    vault = Vault(tmp_path)
    note = vault.new("machine-a draft")
    vault.save(note)
    app = Jotline(vault, initial_note=note)
    async with app.run_test(size=(90, 40)) as pilot:
        app.autosave_timer.stop()
        app.editor().load_text("still writing on this machine")
        inbound = vault.read(note.id)
        inbound.body = "arrived from the other peer"
        vault.save(inbound)
        assert not app.save_current()
        await pilot.pause()
        assert isinstance(app.screen, RecoveryScreen)
        await pilot.click("#preserve-reload")
        await pilot.pause()
        assert app.current.body == "arrived from the other peer"
        recovered = [item for item in vault.notes() if item.id != note.id]
        assert any(item.body == "still writing on this machine" for item in recovered)
        assert vault.read(note.id).body == "arrived from the other peer"


def test_parser_lists_sync_without_cloud():
    help_text = build_parser().format_help().replace("\n", " ")
    assert "Git or Syncthing" in help_text
    assert "Jotline cloud" in help_text
    sync_help = build_parser().parse_args(["sync", "git"])
    assert sync_help.tool == "git"


def test_the_git_recipe_quotes_the_vault_path(tmp_path):
    # The default macOS vault is under "Application Support", so an unquoted
    # cd was wrong out of the box, and a path with shell metacharacters turned
    # a line the reader is told to run into something else.
    spaced = tmp_path / "Application Support" / "jotline" / "notes"
    spaced.mkdir(parents=True)
    assert f"cd '{spaced}'" in git_recipe(spaced)
    hostile = tmp_path / "x;touch PWNED"
    hostile.mkdir()
    assert "cd '" in git_recipe(hostile)
    assert "`cd " + str(hostile) + "`" not in git_recipe(hostile)
