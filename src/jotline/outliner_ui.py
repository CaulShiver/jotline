"""Inline outline writing mode over the application's canonical Markdown editor."""
from __future__ import annotations

import re
from typing import ClassVar
from uuid import uuid4

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, HorizontalScroll
from textual.widgets import Button, Footer, Static, TextArea

from .limits import EDIT_LIMIT_BYTES
from .markdown_editor import MarkdownEditor
from .modal import Modal, Palette
from .outline_session import OutlineSession, patch, revision
from .outline_state import read_state, write_state
from .outline_view import OutlineNode, OutlineView
from .outliner import ANCHOR, Block, Outline, dedent_line, literal_text

ACTIONS = {
    'new_block': 'Insert sibling block', 'new_child': 'Insert child block',
    'continuation': 'Insert continuation line', 'indent': 'Indent selected branches',
    'outdent': 'Outdent selected branches', 'move_up': 'Move selected branches up',
    'move_down': 'Move selected branches down', 'move_to': 'Move selected branches to…',
    'task': 'Toggle task status', 'fold': 'Fold or expand branch',
    'collapse_all': 'Fold all branches', 'expand_all': 'Expand all branches',
    'zoom': 'Focus branch', 'zoom_out': 'Focus parent', 'home': 'Focus whole note',
    'nav_back': 'Previous outline location', 'nav_forward': 'Next outline location',
    'search': 'Find block, including folded branches', 'restore_folds': 'Restore folds after search',
    'select_block': 'Select or deselect branch', 'select_all': 'Select all visible branches',
    'clear_selection': 'Clear branch selection', 'duplicate': 'Duplicate selected branches',
    'group': 'Group selected sibling branches', 'copy': 'Copy selected branches as Markdown',
    'cut': 'Cut selected branches', 'paste_outline': 'Paste clipboard as outline branches',
    'paste_text': 'Paste clipboard as literal block text', 'delete_branch': 'Delete selected branches',
    'merge': 'Merge block into previous sibling', 'reference': 'Copy permanent block reference',
    'insert_link': 'Insert note link', 'snippet': 'Insert snippet', 'follow_reference': 'Open block reference',
    'embed': 'Preview referenced branch', 'inspector': 'Toggle full-height block inspector',
    'undo': 'Undo edit', 'redo': 'Redo edit', 'save': 'Save note', 'done': 'Switch to Markdown',
}


class BlockEditor(MarkdownEditor):
    def check_consume_key(self, key: str, character: str | None = None) -> bool:
        if key in self.screen.command_keys:
            return False
        return super().check_consume_key(key, character)

    async def _on_key(self, event: events.Key) -> None:
        if not self.read_only:
            action = {'enter': 'new_block', 'shift+enter': 'continuation'}.get(event.key)
            if event.key == 'backspace' and self.selection.is_empty and self.cursor_location == (0, 0):
                action = 'merge'
            if action:
                event.stop()
                event.prevent_default()
                getattr(self.screen, 'action_' + action)()
                return
        if event.key in ('up', 'down') and self.selection.is_empty:
            offset = self.wrapped_document.location_to_offset(self.cursor_location)
            if ((event.key == 'up' and offset.y == 0 or
                    event.key == 'down' and offset.y == self.wrapped_document.height - 1) and
                    self.screen.navigate_edit(-1 if event.key == 'up' else 1)):
                event.stop()
                event.prevent_default()
                return
        await super()._on_key(event)

    async def _on_paste(self, event: events.Paste) -> None:
        event.stop()
        event.prevent_default()
        if self.read_only:
            return
        text = event.text.replace('\r\n', '\n')
        if '\n' in text:
            text = literal_text(text)
        self.insert_checked(text)


class OutlinerScreen(Modal[None]):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding('escape', 'back', 'Back', priority=True),
        Binding('tab', 'indent', 'Indent', priority=True),
        Binding('shift+tab', 'outdent', 'Outdent', priority=True),
        Binding('alt+shift+up', 'move_up', 'Move up', priority=True),
        Binding('alt+shift+down', 'move_down', 'Move down', priority=True),
        Binding('ctrl+space', 'fold', 'Fold', priority=True),
        Binding('alt+right', 'zoom', 'Focus branch', priority=True),
        Binding('alt+left', 'zoom_out', 'Parent', priority=True),
        Binding('ctrl+enter', 'task', 'Task', priority=True),
        Binding('ctrl+shift+backspace', 'delete_branch', 'Delete branch', priority=True, show=False),
        Binding('ctrl+z', 'undo', 'Undo', priority=True, show=False),
        Binding('ctrl+y,ctrl+shift+z', 'redo', 'Redo', priority=True, show=False),
        Binding('ctrl+s', 'save', 'Save', priority=True, show=False, id='jotline.save'),
        Binding('ctrl+p', 'commands', 'Commands', priority=True, id='jotline.commands'),
        Binding('ctrl+f', 'search', 'Find block', priority=True),
        Binding('f2', 'edit_block', 'Edit', priority=True),
        Binding('ctrl+tab,ctrl+shift+tab', 'switch_pane', 'Navigate', priority=True, show=False),
        Binding('shift+up', 'extend(-1)', 'Select previous', show=False),
        Binding('shift+down', 'extend(1)', 'Select next', show=False),
    ]
    CSS = """
    OutlinerScreen { background: $background; padding: 1 2 0 2; }
    #outline-title { height: 1; color: $accent; text-style: bold; }
    #outline-breadcrumb { height: 3; }
    #outline-breadcrumb Button { width: auto; min-width: 6; border: none; }
    #outline-tools { height: 3; }
    #outline-tools Button { width: auto; min-width: 7; }
    #outline-body { height: 1fr; layers: rows editor; }
    #outline-tree { width: 100%; height: 100%; layer: rows; }
    #outline-block { layer: editor; position: absolute; border: none; padding: 0;
        background: $surface; width: 100%; height: 1; }
    #outline-block.inspector { border: round $accent; }
    #outline-help { height: auto; max-height: 2; color: $text-muted; }
    #outline-save { height: 1; color: $text-muted; }
    """

    def __init__(self, source: MarkdownEditor):
        super().__init__()
        self.source = source
        self.session = OutlineSession(source.text)
        self.outline = self.session.outline
        self.current = self.outline.at_row(source.cursor_location[0])
        self.zoomed: Block | None = None
        self.nodes = {}
        self.loaded_content = ''
        self.loaded_block = None
        self.selection: set[str] = set()
        self.locations: list[tuple[str | None, str]] = []
        self.location_index = -1
        self.search_folds = None
        self.inspector = False
        self.command_keys = {key for binding in self.BINDINGS if binding.priority for key in binding.key.split(',')}
        self.note_id = ''

    def compose(self) -> ComposeResult:
        yield Static('Outliner · ' + self.app.current.title, id='outline-title', markup=False)
        yield HorizontalScroll(id='outline-breadcrumb')
        with HorizontalScroll(id='outline-tools'):
            for action, label in [('new_block', '+ Block'), ('new_child', '+ Child'), ('fold', 'Fold'),
                                  ('zoom', 'Focus'), ('task', 'Task'), ('search', 'Find'),
                                  ('commands', 'Commands'), ('done', 'Markdown')]:
                yield Button(label, id='outline-' + action)
        with Container(id='outline-body'):
            yield OutlineView(id='outline-tree')
            editor = BlockEditor('', id='outline-block', soft_wrap=True, tab_behavior='indent')
            editor.read_only = self.source.read_only
            editor.show_line_numbers = False
            editor.indent_width = 2
            editor.tooltip = 'Edit this block. Enter splits; Commands includes continuation line and all branch operations.'
            yield editor
        yield Static('Enter edit / split · Tab nest · Shift+Tab unnest · Ctrl+Space fold · Ctrl+P all commands',
                     id='outline-help')
        yield Static('', id='outline-save', markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.note_id = self.app.current.id
        self.source.history.checkpoint()
        self.restore_state()
        self.rebuild()
        self.view().focus()
        self.set_interval(0.5, self.update_save_status)
        # Each outline command can have a portable user-assigned key.
        for name, key in self.app.settings.outline_hotkeys.items():
            self._bindings.key_to_bindings.pop(key, None)
            self._bindings.bind(key, name, ACTIONS[name], show=False, priority=True)
            self.command_keys.add(key)
        self.command_keys.update(self.app.settings.effective_hotkeys.values())
        self.record_location()
        self.call_after_refresh(self.apply_restored_position)

    def apply_restored_position(self):
        cursor = getattr(self, "_restored_cursor", [0, 0])
        if isinstance(cursor, list) and len(cursor) == 2 and all(isinstance(n, int) and n >= 0 for n in cursor):
            self.block_editor().move_cursor(tuple(cursor))
        scroll = getattr(self, "_restored_scroll", 0)
        if isinstance(scroll, int) and scroll >= 0:
            self.view().scroll_to(y=scroll, animate=False)

    def on_screen_resume(self):
        if self.is_mounted:
            self.call_after_refresh(self.update_save_status)

    def view(self) -> OutlineView:
        return self.query_one('#outline-tree', OutlineView)

    def update_save_status(self) -> None:
        if self.app.current.id != self.note_id:
            self.note_id = self.app.current.id
            self.session = OutlineSession(self.source.text)
            self.outline = self.session.outline
            self.current, self.zoomed = self.outline.roots[0], None
            self.selection.clear()
            self.locations.clear()
            self.location_index = -1
            self.loaded_block = None
            self.restore_state()
            self.rebuild()
            self.call_after_refresh(self.apply_restored_position)
        elif self.source.text != self.outline.text:
            self.reparse()
            self.rebuild()
        self.query_one('#outline-save', Static).update(
            self.app._status_message + f' · {len(self.nodes)} blocks' +
            (f' · {len(self.selection)} selected' if self.selection else '') + ' · local Markdown')

    def block_editor(self) -> BlockEditor:
        return self.query_one('#outline-block', BlockEditor)

    @staticmethod
    def label(block: Block) -> Text:
        return Text(next((line.strip() for line in block.content.splitlines() if line.strip()), 'Empty block'))

    def rebuild(self) -> None:
        self.block_rows = self.outline.rows()
        self.nodes = {block: OutlineNode(block) for block in self.outline.walk()}
        if self.current not in self.nodes:
            self.current = self.outline.roots[0]
        if self.zoomed not in self.nodes:
            self.zoomed = None
        self.view().populate([self.zoomed] if self.zoomed else self.outline.roots, self.current, self.selection)
        self.load_block()
        self.breadcrumbs()
        location = self.view().locations.get(self.current.uid)
        if location:
            self.view().scroll_to(y=max(0, location[0] - self.view().size.height // 2), animate=False)
        self.call_after_refresh(self.position_editor)

    def breadcrumbs(self):
        path = []
        block = self.zoomed
        while block:
            path.append(block)
            block = block.parent
        signature = tuple(b.uid for b in path)
        if getattr(self, '_breadcrumb_path', None) == signature:
            return
        self._breadcrumb_path = signature
        bar = self.query_one('#outline-breadcrumb', HorizontalScroll)
        bar.remove_children()
        buttons = [Button('Note', name='root', classes='crumb')]
        buttons.extend(Button('› ' + self.label(b).plain[:36], name=b.uid, classes='crumb') for b in reversed(path))
        bar.mount(*buttons)

    def position_editor(self):
        if not self.is_mounted:
            return
        editor, view = self.block_editor(), self.view()
        location = view.locations.get(self.current.uid)
        if not location:
            editor.display = False
            return
        start, height, indent = location
        y = start - int(view.scroll_y)
        editor.display = editor.has_focus and (self.inspector or 0 <= y < view.size.height)
        if self.inspector:
            editor.styles.offset = (0, 0)
            editor.styles.width = max(12, view.size.width)
            editor.styles.height = max(1, view.size.height)
        else:
            editor.styles.offset = (indent + 2, max(0, y))
            editor.styles.width = max(8, view.scrollable_content_region.width - indent - 4)
            editor.styles.height = max(1, min(height, view.size.height - max(0, y)))

    def load_block(self):
        self.loaded_content = self.current.content
        editor = self.block_editor()
        if self.loaded_block is not self.current or editor.text != self.loaded_content:
            with editor.prevent(TextArea.Changed):
                editor.load_text(self.loaded_content)
        self.loaded_block = self.current

    def reparse(self, *, history=False):
        uid, zoom = self.current.uid, self.zoomed.uid if self.zoomed else None
        row = self.outline.row(self.current)
        self.session.outline = self.outline
        self.outline = self.session.reload(self.source.text, history=history)
        ids = {b.uid: b for b in self.outline.walk()}
        self.current = ids.get(uid) or self.outline.at_row(row)
        self.zoomed = ids.get(zoom)
        self.selection.intersection_update(ids)

    def flush(self) -> bool:
        editor = self.block_editor()
        if editor.text == self.loaded_content:
            return True
        if self.source.read_only:
            return False
        self.session.outline = self.outline
        self.session.remember(self.source.text, self.block_rows)
        old_lines, old_slots = self.current.lines[:], [c.slot for c in self.current.children]
        before_content = self.current.content
        self.current.set_content(editor.text)
        if not self.sync_block(old_lines, old_slots):
            self.current.lines = old_lines
            for child, slot in zip(self.current.children, old_slots):
                child.slot = slot
            return False
        self.loaded_content = editor.text
        # Ordinary typing cannot change block boundaries. Parse structural edits
        # immediately so the live outline and reopened Markdown always agree.
        grammar = r'(?m)^\s*(?:[-+*]\s|\d+[.)]\s|`{3}|~{3}|>|#{1,6}\s)'
        if re.search(grammar, editor.text) or re.search(grammar, before_content):
            cursor = editor.cursor_location
            self.reparse()
            self.rebuild()
            editor.move_cursor(cursor)
        else:
            if len(old_lines) != len(self.current.lines):
                self.block_rows = self.outline.rows()
            self.view().update_block(self.current)
        return True

    def sync_block(self, old_lines, old_slots):
        """Replace contiguous owned text directly; interleaved content uses a bounded diff."""
        if any(slot < len(old_lines) for slot in old_slots):
            return self.sync()
        before = self.source.text
        old = self.outline.newline.join(old_lines)
        new = self.outline.newline.join(self.current.lines)
        if len(before.encode("utf-8")) - len(old.encode("utf-8")) + len(new.encode("utf-8")) > EDIT_LIMIT_BYTES:
            self.notify("Note is too large; shorten this block before continuing.", severity="error")
            return False
        start, end, replacement = patch(old, new)
        row = self.block_rows[self.current]
        a = self.source.location_at(start, old)
        b = self.source.location_at(end, old)
        self.source.replace(replacement, (row + a[0], a[1]), (row + b[0], b[1]))
        self.app.capture_current_buffer()
        return True

    def sync(self) -> bool:
        before, after = self.source.text, self.outline.text
        if before == after:
            return True
        if len(after.encode('utf-8')) > EDIT_LIMIT_BYTES:
            self.notify('Note is too large; shorten this block before continuing.', severity='error')
            return False
        start, end, replacement = patch(before, after)
        self.source.replace(replacement, self.source.location_at(start, before), self.source.location_at(end, before))
        self.app.capture_current_buffer()
        return True

    @on(TextArea.Changed, '#outline-block')
    def edited(self, event):
        event.stop()
        if self.flush():
            self.offer_completion()

    @on(OutlineView.Chosen)
    def highlighted(self, event):
        event.stop()
        self.choose(event.block)

    def choose(self, block):
        if block is self.current or not self.flush():
            return
        self.source.history.checkpoint()
        self.current = next((b for b in self.outline.walk() if b.uid == block.uid), self.current)
        self.view().active = self.current.uid
        self.load_block()
        location = self.view().locations.get(self.current.uid)
        if location:
            y = location[0]
            if y < self.view().scroll_y or y >= self.view().scroll_y + self.view().size.height:
                self.view().scroll_to(y=y, animate=False)
        self.view().refresh()
        self.call_after_refresh(self.position_editor)

    @on(Button.Pressed)
    def button(self, event):
        event.stop()
        key = event.button.id or ''
        if event.button.has_class('crumb'):
            uid = event.button.name
            self.zoomed = next((b for b in self.outline.walk() if b.uid == uid), None)
            self.current = self.zoomed or self.current
            self.record_location()
            self.rebuild()
        elif key.startswith('outline-'):
            getattr(self, 'action_' + key.removeprefix('outline-'))()

    def targets(self):
        return self.outline.selected_roots(self.selection) or [self.current]

    def change(self, operation):
        if self.source.read_only or not self.flush():
            return
        self.source.history.checkpoint()
        self.session.outline = self.outline
        self.session.remember()
        cursor = self.block_editor().cursor_location
        operation()
        self.sync()
        self.reparse()
        self.source.history.checkpoint()
        if self.zoomed and self.current not in set(self.zoomed.walk()):
            self.zoomed = None
        self.rebuild()
        self.block_editor().move_cursor(cursor)

    def action_indent(self):
        self.change(lambda: self.outline.indent_many(self.targets()))

    def action_outdent(self):
        self.change(lambda: [self.outline.outdent(b) for b in reversed(self.targets())])

    def action_move(self, direction):
        self.change(lambda: self.outline.move_many(self.targets(), direction))

    def action_move_up(self):
        self.action_move(-1)

    def action_move_down(self):
        self.action_move(1)

    def action_task(self):
        self.change(lambda: [self.outline.toggle_task(b) for b in self.targets()])

    def action_delete_branch(self):
        def delete():
            targets = self.targets()
            removed = {b for root in targets for b in root.walk()}
            remaining = [b for b in self.outline.walk() if b not in removed]
            for block in targets:
                self.outline.siblings(block).remove(block)
            self.current = remaining[0] if remaining else Block(['- '])
            if not remaining:
                self.outline.roots.append(self.current)
            self.selection.clear()
        self.change(delete)

    def action_new_block(self):
        editor = self.block_editor()
        editing = editor.has_focus
        def add():
            if editing and not self.current.content.strip() and self.current.parent:
                self.outline.outdent(self.current)
                return
            tail = ''
            if editing:
                first, last = sorted((editor.selection.start, editor.selection.end))
                start, end = editor.char_offset(first), editor.char_offset(last)
                if start == end == 0 and editor.text:
                    self.current = self.outline.add_after(self.current, before=True)
                    return
                tail = editor.text[end:]
                self.current.set_content(editor.text[:start])
            self.current = self.outline.add_after(self.current, tail)
        self.change(add)
        self.action_edit_block(end=False)

    def action_new_child(self):
        def add():
            parent = self.current
            self.current = self.outline.add_after(parent)
            self.outline.reparent(self.current, parent)
        self.change(add)
        self.action_edit_block(False)

    def action_continuation(self):
        if not self.block_editor().has_focus:
            self.action_edit_block()
        self.block_editor().insert_checked('\n')

    def action_merge(self):
        def merge():
            siblings = self.outline.siblings(self.current)
            index = siblings.index(self.current)
            if index == 0:
                return
            previous = siblings[index - 1]
            # Fenced/code containers and conflicting task states remain separate.
            if any('```' in b.content or '~~~' in b.content or b.content.startswith('[x]')
                   for b in (previous, self.current)):
                self.notify('This block needs an explicit text edit to merge safely.')
                return
            previous.set_content(previous.content.rstrip() + ' ' + self.current.content.lstrip())
            for child in list(self.current.children):
                self.outline.reparent(child, previous)
            siblings.remove(self.current)
            self.current = previous
        self.change(merge)
        self.action_edit_block()

    def action_edit_block(self, end=True):
        editor = self.block_editor()
        editor.display = True
        editor.focus()
        editor.move_cursor(editor.location_at(len(editor.text)) if end else (0, 0))
        self.position_editor()

    def navigate_edit(self, direction):
        blocks = self.view().blocks
        if self.current not in blocks:
            return False
        index = blocks.index(self.current) + direction
        if not 0 <= index < len(blocks):
            return False
        column = self.block_editor().cursor_location[1]
        self.choose(blocks[index])
        self.action_edit_block(False)
        editor = self.block_editor()
        editor.move_cursor((len(editor.text.split('\n')) - 1 if direction < 0 else 0, column))
        return True

    def action_switch_pane(self):
        if self.block_editor().has_focus:
            self.view().focus()
            self.position_editor()
        else:
            self.action_edit_block()

    def action_fold(self):
        if self.flush() and self.current.children:
            self.current.collapsed = not self.current.collapsed
            self.view().reflow()

    def action_collapse_all(self):
        if self.flush():
            for block in self.outline.walk():
                block.collapsed = True
            self.current = self.zoomed or self.outline.roots[0]
            self.rebuild()

    def action_expand_all(self):
        if self.flush():
            for block in self.outline.walk():
                block.collapsed = False
            self.rebuild()

    def record_location(self):
        value = (self.zoomed.uid if self.zoomed else None, self.current.uid)
        if self.location_index < 0 or self.locations[self.location_index] != value:
            self.locations = self.locations[:self.location_index + 1] + [value]
            self.locations = self.locations[-100:]
            self.location_index = len(self.locations) - 1

    def action_zoom(self):
        if self.flush():
            self.zoomed = self.current
            self.current.collapsed = False
            self.record_location()
            self.rebuild()

    def action_zoom_out(self):
        if self.flush() and self.zoomed:
            self.zoomed = self.zoomed.parent
            self.record_location()
            self.rebuild()

    def action_home(self):
        self.zoomed = None
        self.record_location()
        self.rebuild()

    def navigate_history(self, step):
        index = self.location_index + step
        if 0 <= index < len(self.locations) and self.flush():
            self.location_index = index
            zoom, current = self.locations[index]
            ids = {b.uid: b for b in self.outline.walk()}
            self.zoomed, self.current = ids.get(zoom), ids.get(current, self.current)
            self.rebuild()

    def action_nav_back(self):
        self.navigate_history(-1)

    def action_nav_forward(self):
        self.navigate_history(1)

    def history(self, redo=False):
        if self.source.read_only or not self.flush():
            return
        self.session.outline = self.outline
        self.session.remember()
        self.source.action_redo() if redo else self.source.action_undo()
        self.app.capture_current_buffer()
        self.reparse(history=True)
        # Keep the current branch visible, without expanding unrelated branches.
        parent = self.current.parent
        while parent:
            parent.collapsed = False
            parent = parent.parent
        self.rebuild()

    def action_undo(self):
        self.history()

    def action_redo(self):
        self.history(True)

    def path_label(self, block):
        parts = []
        while block:
            parts.append(self.label(block).plain[:70])
            block = block.parent
        return ' › '.join(reversed(parts))

    def action_search(self):
        if not self.flush():
            return
        choices = [(b.uid, self.path_label(b)) for b in self.outline.walk()]
        def found(uid):
            block = next((b for b in self.outline.walk() if b.uid == uid), None)
            if block:
                if self.search_folds is None:
                    self.search_folds = {b.uid: b.collapsed for b in self.outline.walk()}
                self.zoomed, self.current = None, block
                parent = block.parent
                while parent:
                    parent.collapsed = False
                    parent = parent.parent
                self.record_location()
                self.rebuild()
        self.app.push_screen(Palette(choices, 'Find block · includes folded branches and ancestor paths'), found)

    def action_restore_folds(self):
        if self.search_folds is not None:
            for block in self.outline.walk():
                block.collapsed = self.search_folds.get(block.uid, block.collapsed)
            while self.current.parent and self.current.parent.collapsed:
                self.current = self.current.parent
            self.search_folds = None
            self.rebuild()

    def toggle_selection(self, block):
        if block.uid in self.selection:
            self.selection.remove(block.uid)
        else:
            self.selection.add(block.uid)
        self.view().selected = self.selection
        self.view().refresh()

    def action_select_block(self):
        self.toggle_selection(self.current)

    def action_select_all(self):
        self.selection.update(b.uid for b in self.view().blocks)
        self.view().refresh()

    def action_clear_selection(self):
        self.selection.clear()
        self.view().refresh()

    def action_extend(self, direction):
        if self.block_editor().has_focus:
            return
        blocks = self.view().blocks
        index = blocks.index(self.current) + direction
        self.selection.add(self.current.uid)
        if 0 <= index < len(blocks):
            self.selection.add(blocks[index].uid)
            self.choose(blocks[index])
        self.view().refresh()

    def action_move_to(self):
        excluded = {b for root in self.targets() for b in root.walk()}
        choices = [('root', 'Note root')] + [(b.uid, self.path_label(b)) for b in self.outline.walk() if b not in excluded]
        def picked(uid):
            if uid is not None:
                parent = next((b for b in self.outline.walk() if b.uid == uid), None)
                self.change(lambda: [self.outline.reparent(b, parent) for b in self.targets()])
        self.app.push_screen(Palette(choices, 'Move branches under…'), picked)

    def action_duplicate(self):
        self.change(lambda: [self.outline.duplicate(b) for b in self.targets()])

    def action_group(self):
        def group():
            blocks = self.targets()
            if any(b.parent is not blocks[0].parent for b in blocks):
                self.notify('Select sibling branches to group. Move to… can combine different parents.')
                return
            parent = self.outline.add_after(blocks[0], 'Group', before=True)
            for block in blocks:
                self.outline.reparent(block, parent)
            self.current = parent
            self.selection.clear()
        self.change(group)
        self.action_edit_block()

    def selected_markdown(self):
        return self.outline.newline.join(
            dedent_line(line, block.indent)
            for block in self.targets() for line in block.source_lines())

    def action_copy(self):
        if self.flush():
            self.app.copy_note_text(self.selected_markdown())

    def action_cut(self):
        if not self.source.read_only:
            self.action_copy()
            self.action_delete_branch()

    def action_paste_outline(self):
        text = self.app.clipboard
        if len(text.encode('utf-8')) > EDIT_LIMIT_BYTES:
            self.notify('Clipboard exceeds the note size limit.', severity='error')
            return
        def paste():
            imported = Outline(text)
            siblings = self.outline.siblings(self.current)
            index = siblings.index(self.current) + 1
            for block in imported.roots:
                self.outline.bullet(block)
                block.shift(self.current.indent)
                block.parent, block.slot = self.current.parent, self.current.slot
                for child in block.walk():
                    child.set_content(ANCHOR.sub('', child.content))
            siblings[index:index] = imported.roots
            self.current = imported.roots[0]
        self.change(paste)

    def action_paste_text(self):
        # Escape structural Markdown markers. Explicit outline paste preserves them.
        text = literal_text(self.app.clipboard)
        self.action_edit_block()
        self.block_editor().insert_checked(text)

    def action_inspector(self):
        self.inspector = not self.inspector
        self.block_editor().set_class(self.inspector, 'inspector')
        self.action_edit_block()

    def action_commands(self):
        choices = [(name, label) for name, label in ACTIONS.items()]
        choices += [('app:' + key, label) for key, label in self.app.command_choices() if key != 'outliner']
        def run(key):
            if not key:
                return
            if key.startswith('app:format:'):
                self.block_editor().apply_format(key.removeprefix('app:format:'))
                self.flush()
                self.action_edit_block()
            elif key.startswith('app:'):
                if self.flush():
                    self.persist_state()
                    self.app.command(key.removeprefix('app:'))
            else:
                getattr(self, 'action_' + key)()
        self.app.push_screen(Palette(choices, 'Outliner commands · type to filter'), run)

    def action_reference(self):
        def anchor():
            if not ANCHOR.search(self.current.content):
                self.current.set_content(self.current.content.rstrip() + ' ^' + uuid4().hex[:12])
        self.change(anchor)
        match = ANCHOR.search(self.current.content)
        if match:
            self.app.copy_note_text('[[' + self.app.current.id + '#^' + match[1] + ']]')

    def offer_completion(self):
        editor = self.block_editor()
        offset = editor.char_offset(editor.cursor_location)
        trigger = editor.text[max(0, offset - 2):offset]
        if editor.has_focus and editor.selection.is_empty and trigger in {'[[', ';;'} and self.app.screen is self:
            self.insert_completion(trigger, offset)

    def insert_completion(self, trigger, offset=None):
        from .store import wiki_link
        from .templates import Templates
        editor = self.block_editor()
        original = editor.text
        try:
            choices = (self.app.note_choices(self.app.vault.search(workspace=self.app.workspace)) if trigger == '[[' else
                       [(name, name) for name in Templates(self.app.vault.path).names()])
        except (OSError, ValueError) as error:
            self.notify(str(error), severity='error')
            return
        def complete(key):
            if not key or editor.text != original:
                return
            try:
                body = (wiki_link(self.app.read_in_workspace(key)) if trigger == '[[' else
                        Templates(self.app.vault.path).render(key, self.app.workspace,
                                                             title=self.app.current.title, body=original))
                if offset is not None:
                    editor.move_cursor(editor.location_at(offset - 2))
                    editor.move_cursor(editor.location_at(offset), select=True)
                editor.insert_checked(body)
                self.flush()
                editor.display = True
                editor.focus()
            except (OSError, ValueError) as error:
                self.notify(str(error), severity='error')
        self.app.push_screen(Palette(choices, 'Insert note link' if trigger == '[[' else 'Insert snippet'), complete)

    def action_insert_link(self):
        self.insert_completion('[[')

    def action_snippet(self):
        self.insert_completion(';;')

    def reference_target(self):
        from .links import iter_wiki_links
        links = [link.target for link in iter_wiki_links(self.current.content) if '#^' in link.target]
        return links[0] if links else None

    def action_follow_reference(self):
        if target := self.reference_target():
            self.app.follow_wiki_target(target)
        else:
            self.notify('This block has no permanent block reference.')

    def action_embed(self):
        from .screens import MarkdownPreview
        if target := self.reference_target():
            note_id, anchor = target.split('#^', 1)
            try:
                note = self.app.read_in_workspace(note_id)
                block = next((b for b in Outline(note.body).walk()
                              if (m := ANCHOR.search(b.content)) and m[1] == anchor), None)
                if block:
                    # A read-only, one-level preview cannot recursively expand cycles.
                    self.app.push_screen(MarkdownPreview('\n'.join(block.source_lines())))
                else:
                    self.notify('Referenced block no longer exists.', severity='warning')
            except (OSError, ValueError) as error:
                self.notify(str(error), severity='error')

    def restore_state(self):
        state = read_state(self.app.vault.path / '.jotline-outline.json', self.note_id, self.source.text)
        rows = {row: block for block, row in self.outline.rows().items()}
        folded = state.get('folded', [])
        for row in (folded if isinstance(folded, list) else []):
            if isinstance(row, int) and row in rows:
                rows[row].collapsed = True
        current = state.get('current')
        if isinstance(current, int) and current in rows:
            self.current = rows[current]
        self.zoomed = rows.get(state.get('zoom')) if isinstance(state.get('zoom'), int) else None
        self._restored_cursor = state.get('cursor', [0, 0])
        self._restored_scroll = state.get('scroll', 0)

    def persist_state(self):
        rows = self.outline.rows()
        data = {'revision': revision(self.source.text), 'folded': [row for b, row in rows.items() if b.collapsed],
                'current': rows.get(self.current, 0), 'zoom': rows.get(self.zoomed),
                'cursor': list(self.block_editor().cursor_location), 'scroll': int(self.view().scroll_y)}
        try:
            write_state(self.app.vault.path / '.jotline-outline.json', self.note_id, data)
        except (OSError, ValueError) as error:
            self.notify('Could not save outline view: ' + str(error), severity='warning')

    def action_save(self):
        if self.flush():
            self.app.save_current(explicit=True)
            self.persist_state()
            self.update_save_status()

    def action_back(self):
        if self.block_editor().has_focus:
            self.view().focus()
            self.position_editor()
        else:
            self.action_done()

    def action_done(self):
        if not self.flush():
            return
        self.source.history.checkpoint()
        self.source.move_cursor((self.outline.row(self.current), 0))
        self.app.save_current(explicit=True)
        self.persist_state()
        self.dismiss(None)
        self.source.focus()
