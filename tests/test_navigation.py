import pytest

from textual.widgets import Input, OptionList, Static, TextArea

from jotline.app import Jotline, Palette
from jotline.navigation import ViewEditor, Walkthrough
from jotline.settings import Settings
from jotline.store import Vault


async def test_navigation_and_walkthrough_preserve_capture(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(110, 34)) as pilot:
        editor = app.query_one('#editor', TextArea)
        editor.insert('Unfinished thought')
        await pilot.click('#nav-collections')
        assert isinstance(app.screen, Palette)
        await pilot.press('escape')
        await pilot.click('#nav-help')
        assert isinstance(app.screen, Walkthrough)
        await pilot.press('escape')
        assert editor.text == 'Unfinished thought'
        assert editor.has_focus
        assert all(note.body == "Unfinished thought" for note in app.vault.notes())


async def test_view_rename_duplicate_update_persist_and_mark_modified(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 40)) as pilot:
        app.save_view('review')
        app.apply_view('review')
        app.edit_saved_view('review', 'edit')
        await pilot.pause()
        form = app.screen
        assert isinstance(form, ViewEditor)
        form.query_one('#view-name', Input).value = 'weekly'
        form.query_one('#view-query', Input).value = '#work'
        await pilot.click('#view-save')
        await pilot.pause()
        assert 'review' not in app.settings.saved_views
        assert app.active_view == 'weekly'
        app.edit_saved_view('weekly', 'duplicate')
        await pilot.pause()
        app.screen.query_one('#view-name', Input).value = 'copy'
        await pilot.click('#view-save')
        await pilot.pause()
        assert set(app.settings.saved_views) == {'weekly', 'copy'}
        app.query_one('#search', Input).value = '#changed'
        await pilot.pause()
        assert '(modified)' in str(app.query_one('#collection', Static).render())
        app.update_active_view()
        await pilot.pause()
        await pilot.click('#view-save')
        await pilot.pause()
        assert app.settings.saved_views['copy']['query'] == '#changed'
        assert '(modified)' not in str(app.query_one('#collection', Static).render())
        app.clear_view()
        assert app.active_view is None
    settings, warning = Settings.load(app.settings_path)
    assert not warning
    assert settings.saved_views['weekly']['query'] == '#work'
    assert settings.saved_views['copy']['query'] == '#changed'


async def test_view_form_rejects_invalid_query_and_duplicate_name(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 40)) as pilot:
        app.save_view('existing')
        app.save_view_prompt()
        await pilot.pause()
        form = app.screen
        form.query_one('#view-name', Input).value = 'existing'
        await pilot.click('#view-save')
        assert 'already used' in str(form.query_one('#view-error', Static).render())
        form.query_one('#view-name', Input).value = 'new'
        form.query_one('#view-query', Input).value = 'updated-before:2026-99-99'
        await pilot.click('#view-save')
        assert app.screen is form
        assert 'new' not in app.settings.saved_views
        await pilot.press('escape')
        app.query_one('#search', Input).value = 'updated-before:2026-99-99'
        await pilot.pause()
        assert app.query_one('#notes', OptionList).option_count == 0
        assert 'Fix the search' in str(app.query_one('#empty-notes', Static).render())


@pytest.mark.parametrize("size", [(60, 20), (80, 24)])
async def test_filters_apply_without_creating_view_and_empty_hint(tmp_path, size):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=size) as pilot:
        await pilot.press('ctrl+f')
        await pilot.click('#nav-filters')
        await pilot.pause()
        form = app.screen
        form.query_one('#view-query', Input).value = '#missing'
        form.query_one('#view-query', Input).focus()
        for _ in range(12):
            if getattr(app.focused, 'id', None) == 'view-save':
                break
            await pilot.press('tab')
        assert getattr(app.focused, 'id', None) == 'view-save'
        assert app.focused.region.bottom <= size[1]
        assert app.focused.region.right <= size[0]
        app.save_screenshot(f'jotline-views-{size[0]}x{size[1]}.svg', path='/tmp')
        await pilot.press('enter')
        await pilot.pause()
        assert not app.settings.saved_views
        assert app.query_one('#search', Input).value == '#missing'
        assert 'No matches' in str(app.query_one('#empty-notes', Static).render())
