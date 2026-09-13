"""Markdown editing: highlighting, list continuation and formatting transforms.

The text functions here are pure so they can be tested without a terminal. The
highlighter is a line scanner rather than a tree-sitter grammar: it needs no
compiled dependency, understands inline emphasis, and stays fast enough to
rerun after every keystroke on notes of a few hundred kilobytes.
"""
from __future__ import annotations

from collections import defaultdict
import re

from rich.cells import cell_len
from rich.style import Style
from textual import events
from textual.color import Color
from textual.widgets import TextArea
from textual.widgets.text_area import TextAreaTheme

from .tasks import FENCE

# Above this size the editor stays plain so typing never waits on highlighting.
HIGHLIGHT_MAX_CHARS = 512 * 1024

HEADING = re.compile(r"(?P<indent> {0,3})(?P<marker>#{1,6})(?:(?P<gap>[ \t]+)(?P<text>.*?))?[ \t]*$")
RULE = re.compile(r" {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
QUOTE = re.compile(r"(?P<marker>[ \t]*(?:>[ \t]?)+)")
LIST_ITEM = re.compile(
    r"(?P<indent>[ \t]*)(?P<marker>[-*+]|(?P<number>\d{1,9})(?P<delimiter>[.)]))"
    r"(?P<gap>[ \t]+|$)(?P<task>\[[ xX]\](?:[ \t]+|$))?")
TABLE_SEPARATOR = re.compile(r"[ \t]*\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")

CODE_SPAN = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)")
INLINE = [
    ("bold", re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")),
    ("italic", re.compile(r"(?<![*\w])(\*)(?=[^\s*])(.+?)(?<=[^\s*])\*(?!\*)")),
    ("italic", re.compile(r"(?<![_\w])(_)(?=[^\s_])(.+?)(?<=[^\s_])_(?![_\w])")),
    ("strikethrough", re.compile(r"(~~)(?=\S)(.+?)(?<=\S)~~")),
]
LINK = re.compile(r"(?P<bang>!?)\[(?P<label>[^\]\n]*)\]\((?P<uri>[^)\s]*)(?:[ \t]+\"[^\"\n]*\")?\)")
FOOTNOTE = re.compile(r"\[\^[^\]\s]+\]")
BARE_URL = re.compile(r"<?(?:https?|mailto):[^\s<>()]+>?")
WIKI = re.compile(r"\[\[[^\[\]\n]+\]\]")
TAG = re.compile(r"(?<![\w#&/])#[^\W\d][\w/-]*")

Highlight = tuple[int, int | None, str]


def _bytes(text: str, index: int) -> int:
    return len(text[:index].encode("utf-8"))


def fenced_rows(lines: list[str]) -> set[int]:
    """Rows inside or delimiting a fenced code block."""
    rows, fence = set(), None
    for row, line in enumerate(lines):
        marker = FENCE.fullmatch(line)
        if fence is not None:
            rows.add(row)
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
        elif marker and not (marker[1][0] == "`" and "`" in marker[2]):
            fence = marker[1]
            rows.add(row)
    return rows


def highlight_line(line: str) -> list[Highlight]:
    """Highlights for one line outside fenced code, as UTF-8 byte ranges."""
    spans: list[tuple[int, int, str]] = []
    add = spans.append
    body_start = 0
    if heading := HEADING.match(line):
        add((heading.start("marker"), heading.end("marker"), "heading.marker"))
        if heading["text"]:
            add((heading.start("text"), heading.end("text"), "heading"))
        body_start = heading.end("marker")
    elif RULE.match(line):
        return [(0, len(line.encode("utf-8")), "md.rule")]
    else:
        if (quote := QUOTE.match(line)) and ">" in quote[0]:
            add((0, quote.end(), "md.quote.marker"))
            add((quote.end(), len(line), "md.quote"))
            body_start = quote.end()
        if item := LIST_ITEM.match(line, body_start):
            add((item.start("marker"), item.end("marker"), "list.marker"))
            body_start = item.end()
            if item["task"]:
                done = item["task"][1] in "xX"
                add((item.start("task"), item.start("task") + 3, "md.task.done" if done else "md.task"))
                if done:
                    add((item.end(), len(line), "md.done"))
        if "|" in line and (TABLE_SEPARATOR.fullmatch(line) or line.lstrip().startswith("|")):
            for match in re.finditer(r"(?<!\\)\||(?<=\|)[ \t]*:?-+:?[ \t]*(?=\|)", line):
                add((match.start(), match.end(), "md.table"))

    code = [(match.start(), match.end()) for match in CODE_SPAN.finditer(line, body_start)]
    for start, end in code:
        add((start, end, "inline_code"))

    def free(start: int, end: int) -> bool:
        return all(end <= left or start >= right for left, right in code)

    for name, pattern in INLINE:
        for match in pattern.finditer(line, body_start):
            if free(match.start(), match.end()):
                marker = len(match[1])
                add((match.start(), match.end(), name))
                add((match.start(), match.start() + marker, "md.syntax"))
                add((match.end() - marker, match.end(), "md.syntax"))
    for match in LINK.finditer(line, body_start):
        if free(match.start(), match.end()):
            add((match.start("label"), match.end("label"), "link.label"))
            add((match.start("uri"), match.end("uri"), "link.uri"))
    for pattern, name in ((WIKI, "md.wikilink"), (FOOTNOTE, "link.label"), (TAG, "md.tag")):
        for match in pattern.finditer(line, body_start):
            if free(match.start(), match.end()):
                add((match.start(), match.end(), name))
    for match in BARE_URL.finditer(line, body_start):
        # A URL already inside (…) of a Markdown link is highlighted there.
        if free(match.start(), match.end()) and line[max(match.start() - 1, 0):match.start()] != "(":
            add((match.start(), match.end(), "link.uri"))
    return [(_bytes(line, start), _bytes(line, end), name) for start, end, name in spans if end > start]


def highlight_markdown(lines: list[str]) -> dict[int, list[Highlight]]:
    highlights: dict[int, list[Highlight]] = defaultdict(list)
    fenced = fenced_rows(lines)
    for row, line in enumerate(lines):
        if row in fenced:
            name = "md.fence" if FENCE.fullmatch(line) else "md.code"
            if line:
                highlights[row].append((0, len(line.encode("utf-8")), name))
        elif line:
            highlights[row].extend(highlight_line(line))
    return highlights


def headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """(row, level, title) for every ATX heading outside fenced code."""
    fenced = fenced_rows(lines)
    found = []
    for row, line in enumerate(lines):
        if row not in fenced and (match := HEADING.match(line)) and match["text"]:
            found.append((row, len(match["marker"]), match["text"].rstrip("# \t") or match["text"]))
    return found


def continuation(line: str, column: int) -> tuple[str, bool] | None:
    """What Enter should do on a Markdown list or quote line.

    Returns (prefix for the new line, False), or ("", True) when the item is
    empty and Enter should end the list by clearing its marker. None means an
    ordinary newline.
    """
    quote = QUOTE.match(line)
    quote_prefix = quote[0] if quote and ">" in quote[0] else ""
    item = LIST_ITEM.match(line, len(quote_prefix))
    if item and (item["gap"] or item.end() == len(line)):
        if column < item.end():
            return None
        if not line[item.end():].strip() and column >= len(line.rstrip()):
            return "", True
        marker = item["marker"]
        if item["number"]:
            marker = str(int(item["number"]) + 1) + item["delimiter"]
        gap = item["gap"] if item["gap"] else " "
        task = "[ ] " if item["task"] else ""
        return quote_prefix + item["indent"] + marker + gap + task, False
    if quote_prefix:
        if column < len(quote_prefix):
            return None
        if not line[len(quote_prefix):].strip():
            return "", True
        return quote_prefix, False
    return None


def _strip_block_prefix(line: str) -> tuple[str, str]:
    """Split indentation from a line with any list or task marker removed."""
    item = LIST_ITEM.match(line)
    if item and (item["gap"] or item.end() == len(line)):
        return item["indent"], line[item.end():]
    stripped = line.lstrip(" \t")
    return line[:len(line) - len(stripped)], stripped


def toggle_lines(lines: list[str], style: str) -> list[str]:
    """Apply or remove a block style on each line.

    If every non-blank line already has the style it is removed; otherwise it is
    applied, replacing a different list or heading marker rather than stacking.
    """
    content = [line for line in lines if line.strip()] or lines
    if style.startswith("h") and style[1:].isdigit():
        level = int(style[1:])
        marker = "#" * level + " "
        remove = all((m := HEADING.match(line)) and len(m["marker"]) == level for line in content)
        result = []
        for line in lines:
            heading = HEADING.match(line)
            if not line.strip() and len(lines) > 1:
                result.append(line)
            elif remove:
                result.append(heading["indent"] + (heading["text"] or "") if heading else line)
            else:
                # Replace a different heading level instead of stacking markers.
                result.append(heading["indent"] + marker + (heading["text"] or "") if heading else marker + line)
        return result
    if style == "quote":
        if all(line.lstrip().startswith(">") for line in content):
            return [re.sub(r"^([ \t]*)>[ \t]?", r"\1", line, count=1) for line in lines]
        return ["> " + line if line.strip() or len(lines) == 1 else line for line in lines]

    def has(line: str) -> bool:
        item = LIST_ITEM.match(line)
        if not item or not (item["gap"] or item.end() == len(line)):
            return False
        if style == "task":
            return bool(item["task"])
        if style == "numbered":
            return bool(item["number"]) and not item["task"]
        return not item["number"] and not item["task"]

    remove = all(has(line) for line in content)
    result, number = [], 0
    for line in lines:
        if not line.strip() and len(lines) > 1:
            result.append(line)
            continue
        indent, text = _strip_block_prefix(line)
        if remove:
            result.append(indent + text)
        elif style == "numbered":
            number += 1
            result.append(f"{indent}{number}. {text}")
        else:
            result.append(indent + ("- [ ] " if style == "task" else "- ") + text)
    return result


def indent_lines(lines: list[str], outdent: bool = False) -> list[str]:
    if not outdent:
        return ["  " + line if line.strip() else line for line in lines]
    return [line[2:] if line.startswith("  ") else line[1:] if line[:1] in (" ", "\t") else line
            for line in lines]


def fence_for(text: str) -> str:
    longest = max((len(run) for run in re.findall(r"`{3,}", text)), default=2)
    return "`" * (longest + 1)


def split_cells(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    cells, current, code = [], "", ""
    index = 0
    while index < len(body):
        char = body[index]
        if char == "\\" and index + 1 < len(body):
            current += body[index:index + 2]
            index += 2
            continue
        if char == "`":
            run = re.match(r"`+", body[index:])[0]
            code = "" if code == run else (code or run)
            current += run
            index += len(run)
            continue
        if char == "|" and not code:
            cells.append(current.strip())
            current = ""
        else:
            current += char
        index += 1
    cells.append(current.strip())
    return cells


def table_bounds(lines: list[str], row: int) -> tuple[int, int] | None:
    """First and last row of the pipe table containing ``row``, if any."""
    def is_row(index: int) -> bool:
        return 0 <= index < len(lines) and "|" in lines[index] and bool(lines[index].strip())

    if not is_row(row):
        return None
    first = last = row
    while is_row(first - 1):
        first -= 1
    while is_row(last + 1):
        last += 1
    if last == first or not any(TABLE_SEPARATOR.fullmatch(lines[index]) for index in (first + 1,)):
        return None
    return first, last


def format_table(lines: list[str]) -> list[str]:
    """Align a pipe table: header, separator (keeping alignment colons), rows."""
    rows = [split_cells(line) for line in lines]
    alignments = []
    for cell in rows[1]:
        left, right = cell.startswith(":"), cell.endswith(":")
        alignments.append("center" if left and right else "right" if right else "left" if left else "")
    columns = max(len(row) for row in rows)
    for row in rows:
        row.extend([""] * (columns - len(row)))
    alignments.extend([""] * (columns - len(alignments)))
    widths = [max(3, *(cell_len(row[column]) for index, row in enumerate(rows) if index != 1))
              for column in range(columns)]

    def pad(text: str, width: int, alignment: str) -> str:
        space = width - cell_len(text)
        if alignment == "right":
            return " " * space + text
        if alignment == "center":
            return " " * (space // 2) + text + " " * (space - space // 2)
        return text + " " * space

    output = []
    for index, row in enumerate(rows):
        if index == 1:
            cells = []
            for width, alignment in zip(widths, alignments):
                dashes = "-" * (width - (alignment in ("center", "left")) - (alignment in ("center", "right")))
                cells.append((":" if alignment in ("center", "left") else "") + dashes +
                             (":" if alignment in ("center", "right") else ""))
        else:
            cells = [pad(cell, width, alignment) for cell, width, alignment in zip(row, widths, alignments)]
        output.append("| " + " | ".join(cells) + " |")
    return output


TABLE_TEMPLATE = ["| Column | Column |", "| ------ | ------ |", "|        |        |"]


def _muted(theme, factor: float = 0.45) -> str:
    foreground = Color.parse(theme.foreground or "#d6ddd8")
    background = Color.parse(theme.background or "#101619")
    return foreground.blend(background, factor).hex


def syntax_styles(theme) -> dict[str, Style]:
    """Markdown colours derived from the active app theme."""
    accent = theme.accent or theme.primary
    primary = theme.primary
    secondary = theme.secondary or accent
    warning = theme.warning or secondary
    success = theme.success or primary
    muted = _muted(theme)
    return {
        "heading": Style(color=accent, bold=True),
        "heading.marker": Style(color=muted),
        "bold": Style(bold=True),
        "italic": Style(italic=True),
        "strikethrough": Style(strike=True, color=muted),
        "inline_code": Style(color=warning),
        "md.code": Style(color=warning),
        "md.fence": Style(color=muted),
        "md.syntax": Style(color=muted),
        "link.label": Style(color=primary, underline=True),
        "link.uri": Style(color=muted, underline=True),
        "md.wikilink": Style(color=primary, underline=True),
        "list.marker": Style(color=accent, bold=True),
        "md.task": Style(color=accent, bold=True),
        "md.task.done": Style(color=success, bold=True),
        "md.done": Style(color=muted, strike=True),
        "md.quote.marker": Style(color=accent),
        "md.quote": Style(color=muted, italic=True),
        "md.rule": Style(color=muted),
        "md.table": Style(color=muted),
        "md.tag": Style(color=secondary),
    }


class MarkdownEditor(TextArea):
    """The writing surface: TextArea plus Markdown highlighting and list continuation."""

    THEME_NAME = "jotline-markdown"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.markdown_highlighting = True
        self.smart_lists = True

    def on_mount(self) -> None:
        self._apply_markdown_theme()

    def _apply_markdown_theme(self) -> None:
        self.register_theme(TextAreaTheme(self.THEME_NAME, syntax_styles=syntax_styles(self.app.current_theme)))
        if self.theme == self.THEME_NAME:
            self._set_theme(self.THEME_NAME)
        else:
            self.theme = self.THEME_NAME
        self._line_cache.clear()
        self.refresh()

    def _app_theme_changed(self) -> None:
        if self.is_mounted:
            self.register_theme(TextAreaTheme(self.THEME_NAME, syntax_styles=syntax_styles(self.app.current_theme)))
        super()._app_theme_changed()

    def set_markdown_options(self, *, highlighting: bool, smart_lists: bool) -> None:
        self.smart_lists = smart_lists
        if highlighting != self.markdown_highlighting:
            self.markdown_highlighting = highlighting
            self._build_highlight_map()
            self.refresh()

    def _build_highlight_map(self) -> None:
        self._line_cache.clear()
        highlights = self._highlights
        highlights.clear()
        if not getattr(self, "markdown_highlighting", False):
            return
        lines = self.document.lines
        if sum(len(line) for line in lines) > HIGHLIGHT_MAX_CHARS:
            return
        highlights.update(highlight_markdown(lines))

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter" and self.smart_lists and not self.read_only and self.selection.is_empty:
            row, column = self.cursor_location
            line = self.document.get_line(row)
            action = continuation(line, column)
            if action and row not in fenced_rows(self.document.lines[:row + 1]):
                event.stop()
                event.prevent_default()
                self._restart_blink()
                prefix, clear = action
                if clear:
                    self._replace_via_keyboard("", (row, 0), (row, len(line)))
                else:
                    self._replace_via_keyboard("\n" + prefix, (row, column), (row, column))
                return
        await super()._on_key(event)
