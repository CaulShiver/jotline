"""Virtual, wrapped outline rows with one reusable editor overlay."""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import ClassVar

from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.geometry import Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip

from .outliner import Block


@dataclass
class OutlineNode:
    data: Block

    @property
    def is_expanded(self):
        return not self.data.collapsed


class OutlineView(ScrollView, can_focus=True):
    BINDINGS: ClassVar[list[Binding]] = [Binding('up', 'step(-1)', 'Previous', show=False),
                Binding('down', 'step(1)', 'Next', show=False),
                Binding('home', 'edge(False)', 'First', show=False),
                Binding('end', 'edge(True)', 'Last', show=False),
                Binding('left', 'parent', 'Collapse / parent', show=False),
                Binding('right', 'child', 'Expand / child', show=False),
                Binding('space', 'fold', 'Fold', show=False),
                Binding('enter', 'edit', 'Edit', show=False)]
    DEFAULT_CSS = 'OutlineView { overflow-x: hidden; overflow-y: auto; }'

    class Chosen(Message):
        def __init__(self, block: Block):
            super().__init__()
            self.block = block

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.blocks: list[Block] = []
        self.starts: list[int] = []
        self.lines: list[Text] = []
        self.locations: dict[str, tuple[int, int, int]] = {}
        self.active: str = ''
        self.selected: set[str] = set()
        self.cache = {}
        self.roots = []

    def populate(self, roots, active, selected):
        self.roots, self.active, self.selected = roots, active.uid, selected
        self.reflow()

    def reflow(self):
        if self.size.width <= 0:
            return
        width = max(12, self.scrollable_content_region.width)
        self.blocks, self.starts, self.lines, self.locations = [], [], [], {}
        pending = [(root, 0) for root in reversed(self.roots)]
        cache = {}
        while pending:
            block, depth = pending.pop()
            indent = min(depth * 2, max(0, width - 12))
            content = block.content or 'Empty block'
            key = (block.uid, content, width - indent - 4)
            wrapped = self.cache.get(key)
            if wrapped is None:
                wrapped = []
                for line in content.split('\n'):
                    if cell_len(line) <= max(8, width - indent - 4) and '\t' not in line:
                        wrapped.append(Text(line or ' '))
                    else:
                        wrapped.extend(Text(line or ' ').wrap(self.app.console, max(8, width - indent - 4)))
            cache[key] = wrapped
            start = len(self.lines)
            self.locations[block.uid] = (start, len(wrapped), indent)
            self.blocks.append(block)
            self.starts.append(start)
            for index, line in enumerate(wrapped):
                marker = ('▸' if block.collapsed else '▾') if block.children else '•'
                prefix = ' ' * indent + ((marker + ' ') if index == 0 else '  ')
                self.lines.append(Text(prefix) + line)
            if not block.collapsed:
                pending.extend((child, depth + 1) for child in reversed(block.children))
        self.cache = cache
        self.virtual_size = Size(width, len(self.lines))
        self.refresh()
        self.screen.call_after_refresh(self.screen.position_editor)

    def update_block(self, block):
        location = self.locations.get(block.uid)
        if location is None:
            return
        start, height, indent = location
        width = max(8, self.scrollable_content_region.width - indent - 4)
        wrapped = []
        for line in (block.content or 'Empty block').split('\n'):
            wrapped.extend(Text(line or ' ').wrap(self.app.console, width))
        if len(wrapped) != height:
            self.reflow()
            return
        for index, line in enumerate(wrapped):
            marker = ('▸' if block.collapsed else '▾') if block.children else '•'
            prefix = ' ' * indent + ((marker + ' ') if index == 0 else '  ')
            self.lines[start + index] = Text(prefix) + line
        self.refresh_lines(start, height)
        self.screen.position_editor()

    def render_line(self, y: int) -> Strip:
        row = y + int(self.scroll_y)
        width = self.scrollable_content_region.width
        if row >= len(self.lines):
            return Strip.blank(width, self.rich_style)
        line = self.lines[row].copy()
        index = bisect_right(self.starts, row) - 1
        block = self.blocks[index]
        style = self.rich_style
        if block.uid in self.selected:
            style += Style(reverse=True)
        elif block.uid == self.active:
            style += Style(bold=True)
        segments = self.app.console.render_lines(line, self.app.console.options.update(width=width),
                                                 style=style, pad=True)[0]
        return Strip(segments).adjust_cell_length(width, style)

    def watch_scroll_y(self, old: float, new: float):
        super().watch_scroll_y(old, new)
        if self.is_mounted:
            self.screen.position_editor()

    def on_resize(self):
        self.reflow()

    def choose(self, block):
        self.post_message(self.Chosen(block))

    def action_step(self, direction: int):
        index = next((i for i, b in enumerate(self.blocks) if b.uid == self.active), 0)
        if 0 <= index + direction < len(self.blocks):
            self.choose(self.blocks[index + direction])

    def action_edge(self, end: bool):
        if self.blocks:
            self.choose(self.blocks[-1 if end else 0])

    def action_parent(self):
        block = self.screen.current
        if block.children and not block.collapsed:
            self.screen.action_fold()
        elif block.parent:
            self.choose(block.parent)

    def action_child(self):
        block = self.screen.current
        if block.children:
            if block.collapsed:
                self.screen.action_fold()
            else:
                self.choose(block.children[0])

    def action_fold(self):
        self.screen.action_fold()

    def action_edit(self):
        self.screen.action_edit_block()

    def on_click(self, event: events.Click):
        row = event.y + int(self.scroll_y)
        index = bisect_right(self.starts, row) - 1
        if 0 <= index < len(self.blocks):
            block = self.blocks[index]
            self.choose(block)
            location = self.locations[block.uid]
            if event.x == location[2] and row == location[0] and block.children:
                self.screen.call_after_refresh(self.screen.action_fold)
            if event.ctrl:
                self.screen.toggle_selection(block)
            elif event.chain == 2:
                self.screen.call_after_refresh(self.screen.action_edit_block)

    def on_key(self, event: events.Key):
        if event.character and event.character.isprintable() and event.character != ' ':
            char = event.character.casefold()
            index = next((i for i, b in enumerate(self.blocks) if b.uid == self.active), 0)
            for block in self.blocks[index + 1:] + self.blocks[:index + 1]:
                if block.content.lstrip().casefold().startswith(char):
                    self.choose(block)
                    event.stop()
                    break
