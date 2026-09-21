"""Narrowing the in-app task list by due date, and ticking one off from it.

`jotline tasks --due` and `jotline done` have both worked from the shell since
tasks arrived. Inside the app the only list was every open task at any date,
and the only way to check one off was to navigate to its note and edit the line.
"""
from datetime import date, timedelta

from jotline.app import Jotline, Palette
from jotline.store import Vault
from jotline.tasks import Task, gather


def dates():
    today = date.today()
    return today, (today - timedelta(days=3)).isoformat(), (today + timedelta(days=10)).isoformat()


def vault_with_tasks(tmp_path):
    today, past, future = dates()
    vault = Vault(tmp_path)
    vault.save(vault.new(f'# Bills\n\n- [ ] Pay the water bill due:{past}\n'))
    vault.save(vault.new(f'# Today\n\n- [ ] Call the plumber due:{today.isoformat()}\n'))
    vault.save(vault.new(f'# Later\n\n- [ ] Book the survey due:{future}\n'))
    vault.save(vault.new('# Someday\n\n- [ ] Repaint the hallway\n'))
    return vault


def labels(app, title_fragment):
    screen = app.screen
    assert isinstance(screen, Palette)
    assert title_fragment in screen.heading
    return [label for _, label in screen.choices]


async def test_the_due_list_leaves_out_what_is_not_owed_yet(tmp_path):
    app = Jotline(vault_with_tasks(tmp_path))
    async with app.run_test(size=(110, 34)) as pilot:
        app.show_tasks_due()
        await pilot.pause()
        shown = ' '.join(labels(app, 'Due today or overdue'))
        assert 'water bill' in shown
        assert 'plumber' in shown
        assert 'survey' not in shown
        assert 'hallway' not in shown


async def test_the_full_list_still_holds_everything(tmp_path):
    app = Jotline(vault_with_tasks(tmp_path))
    async with app.run_test(size=(110, 34)) as pilot:
        app.show_tasks()
        await pilot.pause()
        shown = ' '.join(labels(app, 'Open tasks'))
        for text in ('water bill', 'plumber', 'survey', 'hallway'):
            assert text in shown


async def test_a_task_due_today_says_so(tmp_path):
    app = Jotline(vault_with_tasks(tmp_path))
    async with app.run_test(size=(110, 34)) as pilot:
        app.show_tasks()
        await pilot.pause()
        shown = labels(app, 'Open tasks')
        assert any('plumber' in label and 'due today' in label for label in shown)
        assert any('water bill' in label and 'overdue' in label for label in shown)


def test_the_label_distinguishes_today_from_overdue_and_from_later():
    today, past, future = dates()
    app = Jotline.__new__(Jotline)
    overdue = Task('n', 'Bills', 3, 'Pay the water bill', False, past)
    now = Task('n', 'Today', 3, 'Call the plumber', False, today.isoformat())
    later = Task('n', 'Later', 3, 'Book the survey', False, future)
    undated = Task('n', 'Someday', 3, 'Repaint the hallway', False, None)
    assert '(overdue)' in Jotline.task_label(app, overdue, today)
    assert 'due today' in Jotline.task_label(app, now, today)
    assert f'due {future}' in Jotline.task_label(app, later, today)
    assert 'due' not in Jotline.task_label(app, undated, today)


async def test_ticking_a_task_off_the_list_writes_it_to_the_note(tmp_path):
    vault = vault_with_tasks(tmp_path)
    app = Jotline(vault)
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.pause()
        task = next(t for t in gather(vault.search(workspace='default')) if 'plumber' in t.text)
        app.tick_task(task.reference())
        await pilot.pause()
        assert '- [x] Call the plumber' in vault.read(task.note_id).body
        assert not any('plumber' in t.text for t in gather(vault.search(workspace='default')))


async def test_ticking_the_note_on_screen_refreshes_what_is_shown(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('# Today\n\n- [ ] Call the plumber\n')
    vault.save(note)
    app = Jotline(vault)
    async with app.run_test(size=(110, 34)) as pilot:
        app.load_id(note.id)
        await pilot.pause()
        app.tick_task(f'{note.id}:3')
        await pilot.pause()
        assert '- [x] Call the plumber' in app.editor().text


async def test_a_line_that_is_not_a_task_is_reported_and_changes_nothing(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('# Today\n\nJust a paragraph.\n')
    vault.save(note)
    app = Jotline(vault)
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.pause()
        app.tick_task(f'{note.id}:3')
        await pilot.pause()
        assert vault.read(note.id).body == '# Today\n\nJust a paragraph.\n'


async def test_an_empty_due_list_explains_itself_rather_than_opening(tmp_path):
    vault = Vault(tmp_path)
    _, _, future = dates()
    vault.save(vault.new(f'# Later\n\n- [ ] Book the survey due:{future}\n'))
    app = Jotline(vault)
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.pause()
        app.show_tasks_due()
        await pilot.pause()
        assert not isinstance(app.screen, Palette)
