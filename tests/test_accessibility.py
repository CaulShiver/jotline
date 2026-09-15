from textual.app import App
from textual.widgets import TextArea

from jotline.accessibility import COPY_REQUEST, unlabeled_controls
from jotline.action_ui import ActionEditor, ActionReport
from jotline.app import Jotline
from jotline.capture_ui import QuickCapture
from jotline.navigation import ViewEditor, Walkthrough
from jotline.preferences import Preferences
from jotline.recovery_ui import RecoveryScreen
from jotline.screens import FindInNote, RevisionPreview
from jotline.store import Note, Vault
from jotline.workflows import Arrange, SelectNotes

UNICODE_SAMPLE = "café 日本語 مرحبا 👩🏽‍💻 e\u0301"
NFC = "café"
NFD = "cafe\u0301"


def notifications(app):
    return [item.message for item in app._notifications]


async def test_writing_screen_controls_have_names(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        missing = unlabeled_controls(app.screen)
        assert missing == [], [widget.id for widget in missing]
        assert "Note editor" in str(app.editor().tooltip)
        copy = dict(app.command_choices())["copy"]
        assert "OSC 52" in copy


async def test_palette_find_recovery_and_capture_are_named(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert unlabeled_controls(app.screen) == []
        await pilot.press("escape")
        app.push_screen(FindInNote())
        await pilot.pause()
        assert unlabeled_controls(app.screen) == []
        await pilot.press("escape")
        app.push_screen(RecoveryScreen("local draft", "disk draft"))
        await pilot.pause()
        assert unlabeled_controls(app.screen) == []
        assert "unsaved" in str(app.screen.query_one("#recovery-local", TextArea).tooltip)
        await pilot.press("escape")

    capture = QuickCapture("inbox")
    async with capture.run_test() as pilot:
        await pilot.pause()
        assert unlabeled_controls(capture.screen) == []
        assert "Quick capture" in str(capture.query_one("#capture-editor", TextArea).tooltip)


async def test_settings_and_views_are_named(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 36)) as pilot:
        await pilot.press("f1")
        await pilot.pause()
        assert isinstance(app.screen, Preferences)
        assert unlabeled_controls(app.screen) == [], [widget.id for widget in unlabeled_controls(app.screen)]
        assert "Color theme" in str(app.screen.query_one("#pref-theme").tooltip)
        await pilot.press("escape")
        app.push_screen(ViewEditor("", app.current_view(), app.settings))
        await pilot.pause()
        assert unlabeled_controls(app.screen) == []


async def test_actions_history_arrange_and_bulk_are_named(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new("saved body")
    vault.save(note)
    host = App()
    async with host.run_test(size=(90, 40)) as pilot:
        host.push_screen(ActionEditor(vault, note, name="shout"))
        await pilot.pause()
        assert unlabeled_controls(host.screen) == [], [widget.id for widget in unlabeled_controls(host.screen)]
        await pilot.press("escape")
        host.push_screen(ActionReport("Preview", "hello"))
        await pilot.pause()
        assert unlabeled_controls(host.screen) == []
        await pilot.press("escape")
        host.push_screen(RevisionPreview(Note("x", "old version")))
        await pilot.pause()
        assert unlabeled_controls(host.screen) == []
        await pilot.press("escape")
        host.push_screen(Arrange("one\ntwo"))
        await pilot.pause()
        assert unlabeled_controls(host.screen) == []
        await pilot.press("escape")
        host.push_screen(SelectNotes([("a", "Alpha"), ("b", "Beta")]))
        await pilot.pause()
        assert unlabeled_controls(host.screen) == []


async def test_unicode_and_combining_marks_round_trip(tmp_path):
    vault = Vault(tmp_path)
    app = Jotline(vault)
    async with app.run_test() as pilot:
        editor = app.query_one("#editor", TextArea)
        editor.insert(UNICODE_SAMPLE)
        assert app.save_current()
        stored = vault.read(app.current.id)
        assert stored.body == UNICODE_SAMPLE
        editor.move_cursor((0, 0))
        editor.action_cursor_right()
        await pilot.pause()
        assert editor.text == UNICODE_SAMPLE


async def test_nfc_and_nfd_are_stored_exactly(tmp_path):
    vault = Vault(tmp_path)
    app = Jotline(vault)
    async with app.run_test() as pilot:
        editor = app.editor()
        editor.insert(NFC + "\n" + NFD)
        assert app.save_current()
        assert vault.read(app.current.id).body == NFC + "\n" + NFD
        assert NFC != NFD


async def test_copy_describes_osc52_as_a_request(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        app.editor().insert("synthetic note")
        app.command("copy")
        await pilot.pause()
        assert app.clipboard == "synthetic note"
        messages = notifications(app)
        assert any(COPY_REQUEST == message for message in messages)
        assert any("Copy requested" in message and "OSC 52" in message for message in messages)


async def test_ime_standin_paste_does_not_claim_clipboard_success(tmp_path):
    """Paste of already-composed text is the IME stand-in; copy still must not overclaim."""
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        app.editor().insert("日本語")
        app.command("copy")
        await pilot.pause()
        assert app.clipboard == "日本語"
        assert all("successfully" not in message.casefold() for message in notifications(app))


async def test_accessibility_notes_command_is_honest(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        app.command("accessibility")
        await pilot.pause()
        assert isinstance(app.screen, Walkthrough)
        assert "OSC 52" in app.screen.body
        assert "VoiceOver" in app.screen.body and "NVDA" in app.screen.body and "Orca" in app.screen.body
        assert "cannot confirm" in app.screen.body
        await pilot.press("escape")
        assert app.editor().has_focus
