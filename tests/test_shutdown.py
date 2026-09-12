"""Regression for the timer/teardown crash observed on macOS CI."""
from textual.widgets import TextArea
from jotline.app import Jotline
from jotline.store import Vault


async def test_autosave_during_shutdown_does_not_query_removed_widgets(tmp_path, monkeypatch):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        app.autosave_timer.stop()
        app.query_one('#editor', TextArea).insert('café first\nignore\nCAFÉ third')
        await pilot.pause()
        app.command('find')
        await pilot.pause()
        # A live modal must not prevent saving.
        app.autosave()
        assert app.vault.read(app.current.id).body.endswith('CAFÉ third')
        app.dirty = True
        close_all = app._close_all

        async def close_with_timer_tick():
            # _shutdown has already changed the public is_running state here.
            assert not app.is_running
            await app.screen_stack[0].query_one('#brand').remove()
            app.autosave()
            await close_all()

        monkeypatch.setattr(app, '_close_all', close_with_timer_tick)
