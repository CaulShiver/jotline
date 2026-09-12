"""Keyboard-accessible recipe builder and management workflows."""
from copy import deepcopy
from dataclasses import replace

from rich.text import Text
from textual import on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from .modal import Modal
from textual.widgets import Button, Input, Label, OptionList, Select, Static, TextArea

from .actions import BUILTIN_ACTIONS, preview_action, validate_actions
from .action_history import ActionHistory, format_history
from .action_recipes import merge_recipes, read_recipes, write_recipes

STEP_LABELS = {'uppercase': 'Uppercase text', 'lowercase': 'Lowercase text', 'strip': 'Trim surrounding whitespace',
               'quote': 'Quote every line as Markdown',
               'template': 'Render template', 'append': 'Append to another note', 'archive': 'Archive source note',
               'copy': 'Copy to clipboard', 'export': 'Export to a new inbox note (terminal UI)',
               'restore': 'Restore original source text (keep copied/exported output)'}


class ActionReport(Modal):
    BINDINGS = [Binding('escape', 'close', 'Close')]
    CSS = '''
    ActionReport { align: center middle; background: $background 80%; }
    #action-report { width: 90; max-width: 96%; height: 90%; border: round $accent; padding: 1; background: $surface; }
    #action-report TextArea { height: 1fr; }
    '''

    def __init__(self, title, text):
        super().__init__()
        self.title_text, self.report = title, text

    def compose(self):
        with Vertical(id='action-report'):
            yield Label(self.title_text)
            yield TextArea(self.report, read_only=True)
            yield Button('Close', id='report-close')

    @on(Button.Pressed, '#report-close')
    def action_close(self):
        self.dismiss(None)


class ActionEditor(Modal[tuple | None]):
    BINDINGS = [Binding('escape', 'cancel', 'Cancel'), Binding('ctrl+s', 'save', 'Save recipe')]
    CSS = '''
    ActionEditor { align: center middle; background: $background 80%; }
    #action-editor { width: 90; max-width: 98%; height: 95%; border: round $accent; padding: 1; background: $surface; }
    #recipe-steps { height: 7; min-height: 3; }
    #step-value { height: 6; min-height: 3; }
    #action-editor Horizontal { height: auto; width: 1fr; }
    #action-editor Button { min-width: 8; margin-right: 1; }
    #action-editor Static { height: auto; }
    '''

    def __init__(self, vault, note, *, name='', steps=None, selection='', unavailable_names=()):
        super().__init__()
        self.vault, self.note, self.selection = vault, note, selection
        self.recipe_name = name
        self.unavailable_names = set(unavailable_names)
        self.steps = deepcopy(steps or [{'type': 'strip'}])

    def compose(self):
        with VerticalScroll(id='action-editor'):
            yield Label('Action builder · Ctrl+S save · Esc cancel')
            yield Input(self.recipe_name, placeholder='Name: lowercase letters, numbers, hyphens', id='recipe-name')
            yield Static('1. Select a step. 2. Choose its operation and value. 3. Apply step, then preview or save.')
            yield OptionList(id='recipe-steps')
            yield Select([(label, key) for key, label in STEP_LABELS.items()], allow_blank=False, id='step-type')
            yield Static('Template: use {{body}}, {{selection}}, {{title}}, {{date}} or {{template:meeting}}.\nAppend: enter the target note ID from this workspace. Other steps need no value.')
            yield TextArea('', id='step-value')
            yield Button('Choose append target by title', id='step-target')
            with Horizontal():
                yield Button('Apply step', id='step-apply')
                yield Button('Add step', id='step-add')
                yield Button('Remove', id='step-remove')
            with Horizontal():
                yield Button('Up', id='step-up')
                yield Button('Down', id='step-down')
            yield Static('Preview never changes notes or clipboard. Running an action may change the source note; completed external effects cannot be undone together.')
            with Horizontal():
                yield Button('Preview', id='recipe-preview')
                yield Button('Save recipe', variant='primary', id='recipe-save')
                yield Button('Cancel', id='recipe-cancel')

    def on_mount(self):
        self.refresh_steps(0)
        self.query_one('#recipe-name', Input).focus()

    def refresh_steps(self, selected):
        options = self.query_one('#recipe-steps', OptionList)
        options.clear_options()
        options.add_options([Text(f"{index + 1}. {STEP_LABELS[step['type']]}" +
                                 (f" — {step['value'][:60]}" if 'value' in step else ''))
                             for index, step in enumerate(self.steps)])
        options.highlighted = selected if self.steps else None
        if self.steps:
            self.load_step(selected)

    @on(OptionList.OptionHighlighted, '#recipe-steps')
    def highlighted(self, event):
        if event.option_index < len(self.steps):
            self.load_step(event.option_index)

    def load_step(self, index):
        step = self.steps[index]
        self.query_one('#step-type', Select).value = step['type']
        self.query_one('#step-value', TextArea).load_text(step.get('value', ''))

    def apply_step(self):
        index = self.query_one('#recipe-steps', OptionList).highlighted
        if index is None:
            raise ValueError('Add a step first')
        kind = str(self.query_one('#step-type', Select).value)
        step = {'type': kind}
        if kind in {'template', 'append'}:
            step['value'] = self.query_one('#step-value', TextArea).text
            if kind == 'append':
                step['value'] = step['value'].strip()
        validate_actions({'action': [step]})
        self.steps[index] = step
        self.refresh_steps(index)

    @on(Button.Pressed)
    def button(self, event):
        key = event.button.id
        try:
            index = self.query_one('#recipe-steps', OptionList).highlighted
            if key == 'step-apply':
                self.apply_step()
            elif key == 'step-target':
                from .app import Palette
                targets = [(note.id, f'{note.title} · {note.collection} · {note.id}')
                           for note in self.vault.notes()
                           if note.workspace == self.note.workspace and note.id != self.note.id
                           and note.collection != 'trash']
                if not targets:
                    raise ValueError('Create a target note in this workspace first')
                self.app.push_screen(Palette(targets, 'Append target in this workspace'), self.choose_target)
            elif key == 'step-add':
                if len(self.steps) >= 16:
                    raise ValueError('An action supports at most 16 steps')
                if self.steps:
                    self.apply_step()
                self.steps.append({'type': 'strip'})
                self.refresh_steps(len(self.steps) - 1)
            elif key == 'step-remove' and index is not None:
                if len(self.steps) == 1:
                    raise ValueError('Keep at least one step; change its operation instead')
                self.steps.pop(index)
                self.refresh_steps(min(index, len(self.steps) - 1))
            elif key in {'step-up', 'step-down'} and index is not None:
                self.apply_step()
                target = index + (-1 if key == 'step-up' else 1)
                if 0 <= target < len(self.steps):
                    self.steps[index], self.steps[target] = self.steps[target], self.steps[index]
                    self.refresh_steps(target)
            elif key == 'recipe-preview':
                self.apply_step()
                result, effects = preview_action(self.vault, self.note, self.steps, selection=self.selection)
                self.app.push_screen(ActionReport('Preview — no changes made', '\n'.join(effects) +
                    '\n\nTargets, conflicts and permissions are checked when run.\n\nSource text after action:\n\n' +
                    result.body[:20000] + ('\n[Preview truncated at 20,000 characters]' if len(result.body) > 20000 else '')))
            elif key == 'recipe-save':
                self.action_save()
            elif key == 'recipe-cancel':
                self.action_cancel()
        except (ValueError, OSError) as error:
            self.notify(str(error), severity='error')

    def choose_target(self, note_id):
        if note_id:
            self.query_one('#step-type', Select).value = 'append'
            self.query_one('#step-value', TextArea).load_text(note_id)

    def action_save(self):
        try:
            self.apply_step()
            name = self.query_one('#recipe-name', Input).value.strip()
            validate_actions({name: self.steps})
            if name in self.unavailable_names:
                raise ValueError('Action already exists; choose a different name')
            for step in self.steps:
                if step['type'] == 'append':
                    target = self.vault.read(step['value'])
                    if target.id == self.note.id or target.workspace != self.note.workspace or target.collection == 'trash':
                        raise ValueError('Choose another non-trash target note in this workspace')
            self.dismiss((name, deepcopy(self.steps)))
        except (ValueError, OSError) as error:
            self.notify(str(error), severity='error')

    def action_cancel(self):
        self.dismiss(None)


class ActionWorkflowMixin:
    def action_workflow_commands(self):
        return [('action-builder', 'Create action with step-by-step builder', self.create_action_recipe),
                ('action-recipes', 'Use a built-in action recipe', self.builtin_action_recipe),
                ('manage-actions', 'Edit, rename, duplicate or export action', self.manage_action_recipe),
                ('import-actions', 'Import shared action recipes', self.import_action_recipes),
                ('action-history', 'View action run history', self.show_action_history)]

    def open_action_editor(self, name='', steps=None, original=None):
        # Snapshot current unsaved editor text; opening a builder must not save it.
        note = replace(self.current, body=self.query_one('#editor', TextArea).text)
        self.push_screen(ActionEditor(self.vault, note, name=name, steps=steps,
                                      selection=self.query_one('#editor', TextArea).selected_text,
                                      unavailable_names=set(self.settings.actions) - {original}),
                         lambda result: self.store_action_recipe(result, original))

    def create_action_recipe(self):
        self.open_action_editor()

    def builtin_action_recipe(self):
        from .app import Palette
        self.push_screen(Palette([(name, name.replace('-', ' ')) for name in BUILTIN_ACTIONS], 'Choose a starter recipe'),
                         lambda name: self.open_action_editor(name, BUILTIN_ACTIONS[name]) if name else None)

    def store_action_recipe(self, result, original=None):
        if result is None:
            return
        name, steps = result
        try:
            values = deepcopy(self.settings.actions)
            if name != original and name in values:
                raise ValueError('Action already exists; choose a different name')
            if original is not None:
                values.pop(original, None)
            values[name] = steps
            updated = replace(self.settings, actions=values)
            updated.save(self.settings_path)
            self.settings = updated
            self.notify('Action saved. Use Run local action to execute it.')
        except (ValueError, OSError) as error:
            self.notify(str(error), severity='error')
            self.open_action_editor(name, steps, original=original)

    def manage_action_recipe(self):
        from .app import Palette
        if not self.settings.actions:
            self.builtin_action_recipe()
            return
        self.push_screen(Palette([(name, name) for name in self.settings.actions], 'Manage action'), self.action_recipe_options)

    def action_recipe_options(self, name):
        from .app import Palette
        if name:
            self.push_screen(Palette([('edit', 'Edit steps or rename'), ('duplicate', 'Duplicate and edit'),
                                      ('export', 'Export shareable recipe')], name),
                             lambda choice: self.manage_action_choice(name, choice))

    def manage_action_choice(self, name, choice):
        from .app import TextPrompt
        if choice == 'edit':
            self.open_action_editor(name, self.settings.actions[name], original=name)
        elif choice == 'duplicate':
            self.open_action_editor((name[:43] + '-copy'), self.settings.actions[name])
        elif choice == 'export':
            self.push_screen(TextPrompt('Export action recipe (creates a new file)', '/path/to/recipe.json'),
                             lambda path: self.export_action_recipe(path, name))

    def export_action_recipe(self, path, name):
        if path:
            try:
                write_recipes(path, {name: self.settings.actions[name]})
                self.notify('Recipe exported. Review template text and target IDs before sharing.')
            except (ValueError, OSError) as error:
                self.notify(str(error), severity='error')

    def import_action_recipes(self):
        from .app import TextPrompt
        self.push_screen(TextPrompt('Import recipes (adds configuration; does not run actions)', '/path/to/recipe.json'),
                         self.load_action_recipes)

    def load_action_recipes(self, path):
        if path:
            try:
                incoming = read_recipes(path)
                updated = replace(self.settings, actions=merge_recipes(self.settings.actions, incoming))
                updated.save(self.settings_path)
                self.settings = updated
                self.notify(f'Imported {len(incoming)} recipes. Review steps and target IDs before running.')
            except (ValueError, OSError, RecursionError) as error:
                self.notify(str(error), severity='error')

    def show_action_history(self):
        try:
            self.push_screen(ActionReport('Action history', format_history(ActionHistory(self.vault.path).read())))
        except (ValueError, OSError, RecursionError) as error:
            self.notify(str(error), severity='error')
