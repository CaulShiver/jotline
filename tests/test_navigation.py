import pytest

from textual.widgets import Input, OptionList, Static, TextArea

from jotline import app as app_module
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
        app.refresh_notes()
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
        app.refresh_notes()
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
        app.save_screenshot(f'jotline-views-{size[0]}x{size[1]}.svg', path=str(tmp_path))
        await pilot.press('enter')
        await pilot.pause()
        assert not app.settings.saved_views
        assert app.query_one('#search', Input).value == '#missing'
        assert 'No matches' in str(app.query_one('#empty-notes', Static).render())


async def test_typing_in_the_search_box_rebuilds_the_note_list_once_typing_pauses(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    for index in range(2):
        vault.save(vault.new(f'# Note {index} about carrots\n'))
    for index in range(4):
        vault.save(vault.new(f'# Note {index} about turnips\n'))
    refreshes = []
    refresh_notes = Jotline.refresh_notes

    def counted(self):
        refreshes.append(self.query_one('#search', Input).value)
        refresh_notes(self)

    monkeypatch.setattr(Jotline, 'refresh_notes', counted)
    app = Jotline(vault)
    async with app.run_test() as pilot:
        listing = app.query_one('#notes', OptionList)
        app.query_one('#search', Input).focus()
        # A debounce longer than the test proves the keys themselves never rebuild.
        monkeypatch.setattr(app_module, 'SEARCH_DEBOUNCE_SECONDS', 30)
        refreshes.clear()
        await pilot.press(*'carrot')
        assert refreshes == []
        assert listing.option_count == 6

        monkeypatch.setattr(app_module, 'SEARCH_DEBOUNCE_SECONDS', 0.05)
        await pilot.press('s')
        for _ in range(100):
            if refreshes:
                break
            await pilot.pause(0.05)
        assert refreshes == ['carrots']
        assert listing.option_count == 2


async def test_the_note_list_redraws_only_when_its_rows_change(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    for index in range(4):
        vault.save(vault.new(f'# Note {index}\n'))
    redraws = []
    clear_options = OptionList.clear_options

    def counted(self):
        if self.id == 'notes':
            redraws.append(self.option_count)
        return clear_options(self)

    monkeypatch.setattr(OptionList, 'clear_options', counted)
    app = Jotline(vault)
    async with app.run_test() as pilot:
        listing = app.query_one('#notes', OptionList)
        redraws.clear()
        app.refresh_notes()
        assert redraws == []
        assert listing.option_count == 4

        app.editor().load_text('# Kept in the list\n')
        assert app.save_current(explicit=True)
        await pilot.pause()
        assert redraws == [4]
        assert listing.option_count == 5
        assert listing.get_option_at_index(listing.highlighted).id == app.current.id

        # An autosave that leaves every row reading the same must not redraw them.
        app.editor().load_text('# Kept in the list\n\nMore body text that no row shows.\n')
        assert app.save_current(explicit=True)
        await pilot.pause()
        assert redraws == [4]
        assert listing.option_count == 5
        assert listing.get_option_at_index(listing.highlighted).id == app.current.id
