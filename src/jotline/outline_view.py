"""Virtual, wrapped outline rows with one reusable editor overlay."""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import ClassVar

from rich.cells import cell_len
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.geometry import Region, Size
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
        # Wrapped content per block, with the gutter added only when a row is
        # painted. A long outline reflows on every fold; building one prefixed
        # string per source line made that cost scale with the whole note.
        self.wrapped: list[list[str]] = []
        self.gutters: list[tuple[str, str]] = []
        self.locations: dict[str, tuple[int, int, int]] = {}
        self.row_count: int = 0
        self.active: str = ''
        self.selected: set[str] = set()
        self.cache = {}
        self.wrap_width = 0
        self.roots = []
        self._paint_style: Style | None = None

    def populate(self, roots, active, selected):
        self.roots, self.active, self.selected = roots, active.uid, selected
        self.reflow()

    def wrapped_lines(self, content: str, width: int) -> list[str]:
        """Keep plain rows cheap; create Rich text only for wrapping or paint."""
        wrapped = []
        console = self.app.console
        for line in content.split('\n'):
            # An ASCII row occupies one cell per character, which is the common
            # case and skips Rich's cell measurement on every reflow.
            length = len(line) if line.isascii() else cell_len(line)
            if length <= width and '\t' not in line:
                wrapped.append(line or ' ')
            else:
                wrapped.extend(part.plain for part in Text(line or ' ').wrap(console, width))
        return wrapped

    def visible_order(self) -> list[tuple[Block, int]]:
        """Every block a fold leaves on screen, with its depth, top to bottom."""
        order = []
        pending = [(root, 0) for root in reversed(self.roots)]
        while pending:
            block, depth = pending.pop()
            order.append((block, depth))
            if not block.collapsed:
                pending.extend((child, depth + 1) for child in reversed(block.children))
        return order

    def content_width(self, visible: int) -> int:
        """The column rows wrap into, allowing for a scrollbar this pass will add.

        Every visible block takes at least one row, so an outline longer than
        the viewport certainly needs one. Textual only lays the scrollbar out on
        the next refresh, and reading the stale width here re-wrapped the whole
        note the next time anything reflowed.
        """
        width = max(12, self.scrollable_content_region.width)
        bar = self.styles.scrollbar_size_vertical
        if bar and not self.show_vertical_scrollbar and visible > self.size.height:
            width = max(12, width - bar)
        return width

    def reflow(self, *, again: bool = False):
        if self.size.width <= 0:
            return
        order = self.visible_order()
        width = self.content_width(len(order))
        blocks, starts, wrapped_rows, gutters, locations = [], [], [], [], {}
        previous, cache = self.cache, {}
        row = 0
        for block, depth in order:
            indent = min(depth * 2, max(0, width - 12))
            content = block.content or 'Empty block'
            # Wrapping depends only on the text and the column it wraps into,
            # so the cache survives a reparse that hands every block a new uid.
            key = (content, width - indent - 4)
            wrapped = previous.get(key)
            if wrapped is None:
                wrapped = self.wrapped_lines(content, max(8, width - indent - 4))
            cache[key] = wrapped
            locations[block.uid] = (row, len(wrapped), indent)
            blocks.append(block)
            starts.append(row)
            wrapped_rows.append(wrapped)
            marker = ('▸' if block.collapsed else '▾') if block.children else '•'
            pad = ' ' * indent
            gutters.append((pad + marker + ' ', pad + '  '))
            row += len(wrapped)
        self.blocks, self.starts, self.wrapped = blocks, starts, wrapped_rows
        self.gutters, self.locations, self.row_count = gutters, locations, row
        if len(cache) < len(previous):
            # Folding hides most of a large outline. Keep the hidden rows, oldest
            # first out, so expanding a branch again does not re-wrap it.
            retained = {key: value for key, value in previous.items() if key not in cache}
            retained.update(cache)
            while len(retained) > 4 * len(cache) + 512:
                del retained[next(iter(retained))]
            cache = retained
        self.cache = cache
        self.wrap_width = width
        self.virtual_size = Size(width, row)
        self.refresh()
        if not again:
            self.call_after_refresh(self.settle_width)
        self.screen.call_after_refresh(self.screen.position_editor)

    def settle_width(self):
        """Re-wrap once if the laid-out content column was not the predicted one."""
        if self.is_mounted and self.size.width > 0 and self.content_width(len(self.blocks)) != self.wrap_width:
            self.reflow(again=True)

    def update_block(self, block):
        location = self.locations.get(block.uid)
        if location is None:
            return
        start, height, indent = location
        column = (self.wrap_width or max(12, self.scrollable_content_region.width)) - indent - 4
        content = block.content or 'Empty block'
        wrapped = self.wrapped_lines(content, max(8, column))
        if len(wrapped) != height:
            self.reflow()
            return
        self.cache[(content, column)] = wrapped
        self.wrapped[bisect_right(self.starts, start) - 1] = wrapped
        self.refresh_lines(start, height)
        self.screen.position_editor()

    def render_lines(self, crop: Region) -> list[Strip]:
        # Resolving the widget's style walks the CSS tree; do it once a frame
        # rather than once per painted row.
        self._paint_style = self.rich_style
        try:
            return super().render_lines(crop)
        finally:
            self._paint_style = None

    def render_line(self, y: int) -> Strip:
        row = y + int(self.scroll_y)
        width = self.scrollable_content_region.width
        base = self._paint_style if self._paint_style is not None else self.rich_style
        if row >= self.row_count:
            return Strip.blank(width, base)
        index = bisect_right(self.starts, row) - 1
        block = self.blocks[index]
        style = base
        if block.uid in self.selected:
            style += Style(reverse=True)
        elif block.uid == self.active:
            style += Style(bold=True)
        offset = row - self.starts[index]
        first, rest = self.gutters[index]
        # Rows are already wrapped to the content width and carry no markup, so
        # one styled segment replaces a full Rich render per painted line.
        line = (first if offset == 0 else rest) + self.wrapped[index][offset]
        length = len(line) if line.isascii() else cell_len(line)
        return Strip([Segment(line, style)], length).adjust_cell_length(width, style)

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
