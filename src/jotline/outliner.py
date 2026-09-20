"""Lossless CommonMark blocks and whole-branch editing operations.

Raw lines remain authoritative. Children have slots between their parent's own
lines, so a paragraph after a nested list belongs to the parent, not its child.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from uuid import uuid4

from markdown_it import MarkdownIt

from .markdown_editor import list_item

PARSER = MarkdownIt('commonmark', {'maxNesting': 256}).disable('inline')
ANCHOR = re.compile(r'(?:^|\s)\^([a-zA-Z0-9-]+)\s*$')


def _plain_flat_list(lines: list[str]) -> bool:
    """Recognize only nonempty, unindented dash items with plain text starts.

    Every line begins a root item. Numeric starts may contain a same-line
    ordered sublist, which Outline also retains as opaque item text. Other
    markers, empty items, whitespace starts, and continuation lines stay with
    the authoritative CommonMark parser.
    """
    return bool(lines) and all(len(line) > 2 and line.startswith('- ') and line[2].isalnum()
                               for line in lines)


def dedent_line(line: str, width: int) -> str:
    content = line.lstrip(' \t')
    leading = len(line[:len(line) - len(content)].expandtabs(4))
    return ' ' * (leading - width) + content if leading >= width else line


def literal_text(text: str) -> str:
    text = re.sub(r'(?m)^([ \t]*)(\d{1,9})([.)])(?=\s|$)', r'\1\2\\\3', text)
    return re.sub(r'(?m)^([ \t]*)([-+*#>~`])', r'\1\\\2', text)


@dataclass(eq=False)
class Block:
    lines: list[str]
    children: list[Block] = field(default_factory=list)
    parent: Block | None = field(default=None, repr=False)
    collapsed: bool = False
    uid: str = field(default_factory=lambda: uuid4().hex)
    slot: int = 1

    @property
    def indent(self) -> int:
        line = self.lines[0]
        return len(line[:len(line) - len(line.lstrip(' \t'))].expandtabs(4))

    @property
    def prefix(self) -> str:
        line = self.lines[0]
        item = list_item(line)
        if item is None or self.indent >= 4 and self.parent is None:
            return ''
        end = item.start('task') if item['task'] else item.end()
        return line[:end]

    @property
    def content(self) -> str:
        prefix = self.prefix
        width = len(prefix.expandtabs(4))
        return '\n'.join([self.lines[0][len(prefix):],
                          *(dedent_line(line, width) for line in self.lines[1:])])

    def set_content(self, content: str) -> None:
        prefix = self.prefix
        old = self.content.split('\n')
        lines = content.replace('\r\n', '\n').split('\n')
        # Map the boundaries between content segments, keeping trailing parent
        # paragraphs after their children when the first paragraph is edited.
        matches = SequenceMatcher(None, old, lines, autojunk=False).get_opcodes()
        for child in self.children:
            boundary = min(child.slot, len(old))
            delta = 0
            for _, a, b, c, d in matches:
                if b <= boundary:
                    delta = d - b
                elif a < boundary:
                    delta = c - a
                    break
            child.slot = max(1, min(len(lines), boundary + delta))
        self.lines = [prefix + lines[0], *[
            ' ' * len(prefix.expandtabs(4)) + line if line else '' for line in lines[1:]]]

    def walk(self):
        pending = [self]
        while pending:
            block = pending.pop()
            yield block
            pending.extend(reversed(block.children))

    def source_lines(self):
        # Iterative, including interleaved parent text.
        pending: list[Block | str] = [self]
        while pending:
            item = pending.pop()
            if isinstance(item, str):
                yield item
                continue
            entries: list[Block | str] = []
            position = 0
            for child in item.children:
                slot = max(position, min(child.slot, len(item.lines)))
                entries.extend(item.lines[position:slot])
                entries.append(child)
                position = slot
            entries.extend(item.lines[position:])
            pending.extend(reversed(entries))

    def shift(self, amount: int) -> None:
        for block in self.walk():
            shifted = []
            for line in block.lines:
                content = line.lstrip(' \t')
                width = len(line[:len(line) - len(content)].expandtabs(4))
                shifted.append(' ' * max(0, width + amount) + content if line else '')
            block.lines = shifted


class Outline:
    """Raw-line blocks with mixed newlines normalized to the first ending style.

    Uniform LF, CRLF, or CR input round-trips unchanged. Mixed-ending input,
    such as an explicit outline clipboard paste, retains all line content but
    ``text`` joins its lines using the first newline convention encountered.
    """

    def __init__(self, text: str):
        ending = re.search(r'\r\n|\r|\n', text)
        self.newline = ending[0] if ending else '\n'
        self.roots: list[Block] = []
        # CommonMark recognizes all three newline conventions. Clipboard text
        # may mix them; use the same row boundaries and normalize on output.
        lines = re.split(r'\r\n|\r|\n', text)
        items = lines[:-1] if lines[-1] == '' else lines
        if _plain_flat_list(items):
            self.roots = [Block([line]) for line in items]
            if lines[-1] == '':
                self.roots[-1].lines.append('')
            return
        tokens = PARSER.parse(text)
        ranges: dict[Block, tuple[int, int]] = {}
        stack: list[Block | None] = []
        opaque_blocks: set[Block] = set()
        opaque_depth = 0
        for token in tokens:
            if token.type == 'blockquote_open':
                opaque_depth += 1
            elif token.type == 'blockquote_close':
                opaque_depth -= 1
            if token.type == 'list_item_open':
                start, end = token.map
                parent = stack[-1] if stack else None
                # A nested list can start on its parent's marker line ("- - A").
                # Rows cannot own overlapping source slices; keep that entire
                # nested list as opaque parent content instead.
                if parent and ranges[parent][0] == start:
                    opaque_blocks.add(parent)
                if (opaque_depth or stack and parent is None or parent in opaque_blocks
                        or not list_item(lines[start])):
                    stack.append(None)
                    continue
                # Separators do not belong to the deleted/moved child.
                while end > start + 1 and not lines[end - 1].strip():
                    end -= 1
                block = Block([], parent=parent)
                ranges[block] = (start, end)
                (parent.children if parent else self.roots).append(block)
                stack.append(block)
            elif token.type == 'list_item_close':
                stack.pop()
        # Populate raw own lines, and record the insertion point of each child.
        for block, (start, end) in ranges.items():
            position = start
            for child in block.children:
                a, b = ranges[child]
                block.lines.extend(lines[position:a])
                child.slot = len(block.lines)
                position = b
            block.lines.extend(lines[position:end])
        # Preserve all non-list containers verbatim as ordinary Markdown blocks.
        roots = self.roots
        self.roots = []
        position = 0
        for root in roots:
            start, end = ranges[root]
            self._gap(lines[position:start])
            self.roots.append(root)
            position = end
        self._gap(lines[position:])
        if not self.roots:
            self.roots = [Block([''])]

    def _gap(self, lines: list[str]) -> None:
        if not lines:
            return
        if self.roots and not any(line.strip() for line in lines):
            self.roots[-1].lines.extend(lines)
        else:
            self.roots.append(Block(lines))

    def walk(self):
        for root in self.roots:
            yield from root.walk()

    @property
    def text(self) -> str:
        return self.newline.join(line for root in self.roots for line in root.source_lines())

    def rows(self) -> dict[Block, int]:
        result = {}
        pending: list[Block | str] = list(reversed(self.roots))
        row = 0
        while pending:
            item = pending.pop()
            if isinstance(item, str):
                row += 1
                continue
            result[item] = row
            entries: list[Block | str] = []
            position = 0
            for child in item.children:
                slot = max(position, min(child.slot, len(item.lines)))
                entries.extend(item.lines[position:slot])
                entries.append(child)
                position = slot
            entries.extend(item.lines[position:])
            pending.extend(reversed(entries))
        return result

    def row(self, target: Block) -> int:
        return self.rows().get(target, 0)

    def at_row(self, row: int) -> Block:
        result = self.roots[0]
        for block, start in sorted(self.rows().items(), key=lambda pair: pair[1]):
            if start > row:
                break
            # Ascend out of the child's source range for trailing parent text.
            result = block
        while result.parent and row >= self.row(result) + len(list(result.source_lines())):
            result = result.parent
        return result

    def siblings(self, block: Block) -> list[Block]:
        return block.parent.children if block.parent else self.roots

    def move(self, block: Block, direction: int) -> bool:
        siblings = self.siblings(block)
        index = siblings.index(block)
        other = index + direction
        if not 0 <= other < len(siblings):
            return False
        block.slot, siblings[other].slot = siblings[other].slot, block.slot
        siblings[index], siblings[other] = siblings[other], block
        return True

    def indent_many(self, blocks: list[Block]) -> None:
        selected = set(blocks)
        destinations = []
        for block in blocks:
            siblings = self.siblings(block)
            index = siblings.index(block) - 1
            while index >= 0 and siblings[index] in selected:
                index -= 1
            if index >= 0:
                destinations.append((block, siblings[index]))
        for block, parent in destinations:
            self.reparent(block, parent)

    def move_many(self, blocks: list[Block], direction: int) -> None:
        selected = set(blocks)
        ordered = blocks if direction < 0 else list(reversed(blocks))
        for block in ordered:
            siblings = self.siblings(block)
            other = siblings.index(block) + direction
            if 0 <= other < len(siblings) and siblings[other] not in selected:
                self.move(block, direction)

    def indent(self, block: Block) -> bool:
        siblings = self.siblings(block)
        index = siblings.index(block)
        if not index:
            return False
        return self.reparent(block, siblings[index - 1])

    def reparent(self, block: Block, parent: Block | None) -> bool:
        if parent in set(block.walk()):
            return False
        self.bullet(block)
        if parent:
            self.bullet(parent)
        self.siblings(block).remove(block)
        block.shift((len(parent.prefix.expandtabs(4)) if parent else 0) - block.indent)
        block.parent = parent
        block.slot = len(parent.lines) if parent else 1
        (parent.children if parent else self.roots).append(block)
        if parent:
            # CommonMark forbids an empty item or a non-1 ordered item from
            # interrupting a paragraph. A separator makes the intended child
            # explicit and keeps preview, export and reopened outlines aligned.
            item = list_item(block.lines[0])
            if parent.lines[-1].strip() and (not block.content.strip() or
                                            item and item['number'] and item['number'] != '1'):
                parent.lines.append('')
                block.slot = len(parent.lines)
            parent.collapsed = False
        return True

    def outdent(self, block: Block) -> bool:
        parent = block.parent
        if parent is None:
            return False
        parent.children.remove(block)
        self.bullet(block)
        block.shift(parent.indent - block.indent)
        siblings = self.siblings(parent)
        block.parent = parent.parent
        block.slot = parent.slot
        siblings.insert(siblings.index(parent) + 1, block)
        return True

    @staticmethod
    def bullet(block: Block) -> None:
        if not block.prefix:
            content = block.content
            block.lines = ['- ']
            block.set_content(content)

    def add_after(self, block: Block, content: str = '', *, before: bool = False) -> Block:
        self.bullet(block)
        item = list_item(block.lines[0])
        marker = (str(int(item['number']) + 1) + item['delimiter']) if item['number'] else item['marker']
        new = Block([' ' * block.indent + marker + ' '], parent=block.parent, slot=block.slot)
        new.set_content(content)
        siblings = self.siblings(block)
        siblings.insert(siblings.index(block) + (0 if before else 1), new)
        return new

    def toggle_task(self, block: Block) -> None:
        self.bullet(block)
        content = block.content
        match = re.match(r'^\[([ xX])\](?: |$)', content)
        content = (('[x] ' if match[1] == ' ' else '[ ] ') + content[match.end():]
                   if match else '[ ] ' + content)
        block.set_content(content)

    def selected_roots(self, selected: set[str]) -> list[Block]:
        roots = []
        for block in self.walk():
            if block.uid not in selected:
                continue
            parent = block.parent
            while parent and parent.uid not in selected:
                parent = parent.parent
            if parent is None:
                roots.append(block)
        return roots

    def duplicate(self, block: Block) -> Block:
        # Clone the existing structure. Dedenting and reparsing opaque code can
        # turn it into several roots and silently discard all but the first.
        clone = Block(block.lines[:], parent=block.parent, slot=block.slot)
        pending = [(block, clone)]
        while pending:
            original, copied = pending.pop()
            for child in original.children:
                descendant = Block(child.lines[:], parent=copied, slot=child.slot)
                copied.children.append(descendant)
                pending.append((child, descendant))
        for descendant in clone.walk():
            content = ANCHOR.sub('', descendant.content)
            if content != descendant.content:
                descendant.set_content(content)
        siblings = self.siblings(block)
        siblings.insert(siblings.index(block) + 1, clone)
        return clone

    def reconcile(self, previous: Outline) -> None:
        """Retain identity only for unambiguous matches and unchanged line runs."""
        old, new = list(previous.walk()), list(self.walk())
        old_counts, new_counts = Counter(b.content for b in old), Counter(b.content for b in new)
        unique = {b.content: b for b in old if old_counts[b.content] == 1}
        used = set()
        for block in new:
            candidate = unique.get(block.content) if new_counts[block.content] == 1 else None
            if candidate:
                block.uid, block.collapsed = candidate.uid, candidate.collapsed
                used.add(candidate.uid)
        # Commands supply stable objects before reparsing; matching source rows
        # handles an edited label without guessing between identical siblings.
        old_rows = {row: block for block, row in previous.rows().items()}
        for block, row in self.rows().items():
            candidate = old_rows.get(row)
            if block.uid not in used and candidate and candidate.uid not in used:
                block.uid, block.collapsed = candidate.uid, candidate.collapsed
                used.add(candidate.uid)
