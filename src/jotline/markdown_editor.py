"""Markdown editing: highlighting, list continuation and formatting transforms.

The text functions here are pure so they can be tested without a terminal. The
highlighter is a line scanner rather than a tree-sitter grammar: it needs no
compiled dependency, understands inline emphasis, and after an edit only the
rows the edit touched are scanned again, so typing never waits on the rest of
the note.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
import re

from rich.cells import cell_len
from rich.style import Style
from textual import events
from textual.binding import Binding
from textual.color import Color
from textual.theme import Theme
from textual.widgets import TextArea
from textual.widgets.text_area import Edit, TextAreaTheme

from .limits import EDIT_LIMIT_BYTES
from .store import LINK as WIKI, TAG
from .tasks import CODE_SPAN, FENCE, TASK, closes_fence, fenced_rows, set_done

# Above this size the editor stays plain so typing never waits on highlighting.
HIGHLIGHT_MAX_CHARS = 512 * 1024

# The default palette, shared by the main app and the quick-capture window.
JOTLINE_THEME = Theme(name="jotline", primary="#a8d5a2", accent="#a8d5a2", foreground="#d6ddd8",
                      background="#101619", surface="#162024", panel="#162024")

HEADING = re.compile(r"(?P<indent> {0,3})(?P<marker>#{1,6})(?:(?P<gap>[ \t]+)(?P<text>.*))?$")
# A closing run of # counts only after whitespace, so "C#" keeps its hash.
CLOSING_HASHES = re.compile(r"(?:^|(?<=[ \t]))#+[ \t]*$")
SETEXT = re.compile(r" {0,3}(=+|-+)[ \t]*$")
RULE = re.compile(r" {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
QUOTE = re.compile(r"(?P<marker>[ \t]*(?:>[ \t]?)+)")
# The gap group takes whitespace or the end of the line, so a match already
# guarantees the marker is a list marker rather than the start of a word.
LIST_ITEM = re.compile(
    r"(?P<indent>[ \t]*)(?P<marker>[-*+]|(?P<number>\d{1,9})(?P<delimiter>[.)]))"
    r"(?P<gap>[ \t]+|$)(?P<task>\[[ xX]\](?:[ \t]+|$))?")
TABLE_SEPARATOR = re.compile(r"[ \t]*\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")

INLINE = [
    ("bold", re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")),
    ("italic", re.compile(r"(?<![*\w])(\*)(?=[^\s*])(.+?)(?<=[^\s*])\*(?!\*)")),
    ("italic", re.compile(r"(?<![_\w])(_)(?=[^\s_])(.+?)(?<=[^\s_])_(?![_\w])")),
    ("strikethrough", re.compile(r"(~~)(?=\S)(.+?)(?<=\S)~~")),
]
LINK = re.compile(r"(?P<bang>!?)\[(?P<label>[^\]\n]*)\]\((?P<uri>[^)\s]*)(?:[ \t]+\"[^\"\n]*\")?\)")
FOOTNOTE = re.compile(r"\[\^[^\]\s]+\]")
BARE_URL = re.compile(r"<?(?:https?|mailto):[^\s<>()]+>?")
# Marker runs that a wrap command removes again. Emphasis checks the whole run
# so italic never strips half of a bold marker.
UNWRAP_RUNS = {"bold": {"**", "__", "***", "___"}, "italic": {"*", "_", "***", "___"}, "strike": {"~~"}}

Highlight = tuple[int, int | None, str]


def _bytes(text: str, index: int) -> int:
    return len(text[:index].encode("utf-8"))


def list_item(line: str, pos: int = 0) -> re.Match | None:
    """The list marker at ``pos``, unless the line is a thematic break like ``- - -``."""
    if RULE.match(line, pos):
        return None
    return LIST_ITEM.match(line, pos)


def heading_title(text: str) -> str:
    return CLOSING_HASHES.sub("", text).strip()


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
    protected = code
    protected_starts = [start for start, _ in protected]
    for start, end in code:
        add((start, end, "inline_code"))

    def free(start: int, end: int) -> bool:
        # Protected ranges are sorted and disjoint; only neighbours can overlap.
        index = bisect_right(protected_starts, start)
        if index and protected[index - 1][1] > start:
            return False
        return index == len(protected) or protected[index][0] >= end

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
    for match in BARE_URL.finditer(line, body_start):
        # A URL already inside (…) of a Markdown link is highlighted there.
        if free(match.start(), match.end()) and line[max(match.start() - 1, 0):match.start()] != "(":
            add((match.start(), match.end(), "link.uri"))
    # Tags and wiki links also leave URL destinations alone. Merge overlaps so
    # checking many tags on a long line stays logarithmic per match.
    protected = []
    for start, end in sorted([*code, *((start, end) for start, end, name in spans if name == "link.uri")]):
        if protected and start <= protected[-1][1]:
            protected[-1] = (protected[-1][0], max(end, protected[-1][1]))
        else:
            protected.append((start, end))
    protected_starts = [start for start, _ in protected]
    for pattern, name in ((WIKI, "md.wikilink"), (FOOTNOTE, "link.label"), (TAG, "md.tag")):
        for match in pattern.finditer(line, body_start):
            if free(match.start(), match.end()):
                add((match.start(), match.end(), name))
    spans = [span for span in spans if span[1] > span[0]]
    if line.isascii():
        return spans
    return [(_bytes(line, start), _bytes(line, end), name) for start, end, name in spans]


def highlight_fenced(line: str) -> list[Highlight]:
    name = "md.fence" if FENCE.fullmatch(line) else "md.code"
    return [(0, len(line.encode("utf-8")), name)] if line else []


def highlight_markdown(lines: list[str], fenced: set[int] | None = None) -> dict[int, list[Highlight]]:
    highlights: dict[int, list[Highlight]] = defaultdict(list)
    if fenced is None:
        fenced = fenced_rows(lines)
    for row, line in enumerate(lines):
        if row in fenced:
            highlights[row].extend(highlight_fenced(line))
        elif line:
            highlights[row].extend(highlight_line(line))
    return highlights


def headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """(row, level, title) for every ATX or setext heading outside fenced code."""
    fenced = fenced_rows(lines)
    found = []
    previous = ""
    for row, line in enumerate(lines):
        if row in fenced:
            previous = ""
        elif match := HEADING.match(line):
            if title := heading_title(match["text"] or ""):
                found.append((row, len(match["marker"]), title))
            previous = ""
        elif previous.strip() and (underline := SETEXT.fullmatch(line)):
            found.append((row - 1, 1 if underline[1][0] == "=" else 2, previous.strip()))
            previous = ""
        else:
            # Only a paragraph line can be underlined; "---" after a list item or
            # quote is a rule.
            previous = ("" if list_item(line) or RULE.match(line) or line.startswith(("    ", "\t"))
                        or line.lstrip().startswith((">", "|")) else line)
    return found


def continuation(line: str, column: int) -> tuple[str, bool] | None:
    """What Enter should do on a Markdown list or quote line.

    Returns (prefix for the new line, False), or ("", True) when the item is
    empty and Enter should end the list by clearing its marker. None means an
    ordinary newline.
    """
    quote = QUOTE.match(line)
    quote_prefix = quote[0] if quote and ">" in quote[0] else ""
    if RULE.match(line, len(quote_prefix)):
        return None
    if item := list_item(line, len(quote_prefix)):
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


def _strip_block_prefix(line: str, keep_task: bool = False) -> tuple[str, str]:
    """Split indentation from a line with its list marker (and checkbox, unless kept) removed."""
    if item := list_item(line):
        text = line[item.end():]
        if keep_task and item["task"]:
            text = item["task"] + text
        return item["indent"], text
    stripped = line.lstrip(" \t")
    return line[:len(line) - len(stripped)], stripped


def toggle_lines(lines: list[str], style: str) -> list[str]:
    """Apply or remove a block style on each line.

    If every non-blank line already has the style it is removed; otherwise it is
    applied, replacing a different list or heading marker rather than stacking.
    A numbered list keeps task checkboxes (``1. [x] done``); a bullet list drops
    them, which is how a task list becomes plain bullets.
    """
    content = [line for line in lines if line.strip() and not RULE.match(line)]
    if not content:
        content = [line for line in lines if not RULE.match(line)]
    skip_blank = len(lines) > 1
    if level_match := re.fullmatch(r"h([1-6])", style):
        level = int(level_match[1])
        marker = "#" * level + " "
        remove = all((m := HEADING.match(line)) and len(m["marker"]) == level for line in content)
        result = []
        for line in lines:
            heading = HEADING.match(line)
            if RULE.match(line) or (not line.strip() and skip_blank):
                result.append(line)
            elif remove:
                result.append(heading["indent"] + heading_title(heading["text"] or "") if heading else line)
            else:
                # Replace a different heading level instead of stacking markers.
                result.append(heading["indent"] + marker + heading_title(heading["text"] or "") if heading
                              else marker + line)
        return result
    if style == "quote":
        if all(line.lstrip().startswith(">") for line in content):
            return [re.sub(r"^([ \t]*)>[ \t]?", r"\1", line, count=1) for line in lines]
        return ["> " + line if not RULE.match(line) and (line.strip() or len(lines) == 1) else line
                for line in lines]

    def has(line: str) -> bool:
        if not (item := list_item(line)):
            return False
        if style == "task":
            return bool(item["task"])
        if style == "numbered":
            return bool(item["number"])
        return not item["number"] and not item["task"]

    remove = all(has(line) for line in content)
    result, number = [], 0
    for line in lines:
        if RULE.match(line) or (not line.strip() and skip_blank):
            result.append(line)
            continue
        indent, text = _strip_block_prefix(line, keep_task=style == "numbered" and not remove)
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
    return [re.sub(r"^(?:  ?|\t)", "", line) for line in lines]


def fence_for(text: str) -> str:
    longest = max((len(run) for run in re.findall(r"`{3,}", text)), default=2)
    return "`" * (longest + 1)


def unwrap_span(style: str, text: str, begin: int, finish: int) -> tuple[int, int, str] | None:
    """If the selection is already formatted with ``style``, the span to replace and its content.

    Both a selection of the inner text and one that includes the markers count.
    """
    body = text[begin:finish]
    if style == "code":
        # A selection that includes backticks is literal text to quote, so
        # only a selection inside an existing code span removes it.
        before = len(text[:begin]) - len(text[:begin].rstrip("`"))
        after = len(text[finish:]) - len(text[finish:].lstrip("`"))
        if before and before == after:
            inner = body[1:-1] if body.startswith(" ") and body.endswith(" ") and len(body) > 1 else body
            if text[begin - before - 1:begin - before] != "`":
                return begin - before, finish + after, inner
        return None
    runs = UNWRAP_RUNS[style]
    size = 1 if style == "italic" else 2
    leading = re.match(r"[*_~]+", body)
    trailing = re.search(r"[*_~]+$", body)
    if leading and trailing and leading.end() < trailing.start() and leading[0] == trailing[0][::-1] \
            and leading[0] in runs:
        run = leading[0]
        inner = body[len(run):len(body) - len(run)]
        if run not in inner:
            keep = run[:len(run) - size]
            return begin, finish, keep + inner + keep
    before = re.search(r"[*_~]+$", text[:begin])
    after = re.match(r"[*_~]+", text[finish:])
    if before and after and before[0] == after[0][::-1] and before[0] in runs:
        return begin - size, finish + size, body
    return None


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
    """First and last row of the pipe table containing ``row``, if any.

    The table is anchored on its separator row so a paragraph above the table
    that happens to contain a pipe is not taken for part of it.
    """
    def is_row(index: int) -> bool:
        return 0 <= index < len(lines) and "|" in lines[index] and bool(lines[index].strip())

    def is_separator(index: int) -> bool:
        return is_row(index) and bool(TABLE_SEPARATOR.fullmatch(lines[index]))

    if not is_row(row):
        return None
    first = row
    while is_row(first - 1):
        first -= 1
    separator = first + 1
    while is_row(separator) and not is_separator(separator):
        separator += 1
    if not (is_separator(separator) and is_row(separator - 1) and separator - 1 <= row):
        return None
    first, last = separator - 1, separator
    while is_row(last + 1):
        last += 1
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


def _rich_color(value: str | None, fallback: str):
    """Translate Textual's ANSI aliases into colors Rich can render."""
    return Color.parse(value or fallback).rich_color


def _muted(theme, factor: float = 0.45):
    """The foreground blended into the background, for markers and syntax."""
    colors = theme.to_color_system().generate()
    foreground = Color.parse(colors["foreground"])
    background = Color.parse(colors["background"])
    return foreground.blend(background, factor).rich_color


def syntax_styles(theme) -> dict[str, Style]:
    """Markdown colours derived from the active app theme."""
    accent = _rich_color(theme.accent or theme.primary, "#a8d5a2")
    primary = _rich_color(theme.primary, "#a8d5a2")
    secondary = _rich_color(theme.secondary, theme.accent or theme.primary or "#a8d5a2")
    warning = _rich_color(theme.warning, theme.secondary or theme.accent or theme.primary or "#a8d5a2")
    success = _rich_color(theme.success, theme.primary or "#a8d5a2")
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
    """The writing surface: TextArea plus Markdown highlighting and list continuation.

    Textual rebuilds the highlight map after every edit. The base class does
    that from a tree-sitter query; here the map is kept by hand, and after an
    ordinary edit only the rows it touched are scanned again. A full rescan
    happens when text is loaded, on undo and redo, and when an edit adds or
    removes a fence line, since that can change which rows are code.
    """

    THEME_NAME = "jotline-markdown"
    BINDINGS = [
        Binding("ctrl+tab", "app.focus_next", "Next control", show=False),
        Binding("ctrl+shift+tab", "app.focus_previous", "Previous control", show=False),
    ]
    # Class-level defaults: TextArea.__init__ builds the highlight map before a
    # subclass __init__ could run, so these must exist on the class.
    markdown_highlighting = True
    smart_lists = True
    _pending_edit: Edit | None = None
    # Fence state of the current highlight map; None when the map is not built.
    _fenced: set[int] | None = None
    _fence_markers: set[int] = set()

    def on_mount(self) -> None:
        self._register_markdown_theme()
        self.theme = self.THEME_NAME

    def _register_markdown_theme(self) -> None:
        theme = self.app.current_theme
        background = Color.parse(self.app.get_css_variables()["background"])
        primary = Color.parse(theme.primary)
        accent = Color.parse(theme.accent or theme.primary)
        # Only tint the selection background so Markdown keeps its theme colours.
        # ANSI palettes cannot blend RGB colours; retain terminal-native reversal.
        selection = (Style(reverse=True) if theme.ansi else
                     Style(bgcolor=background.blend(primary, 0.30).rich_color))
        cursor = accent
        if 'jotline-selection-background' in theme.variables:
            selection = Style(bgcolor=Color.parse(theme.variables['jotline-selection-background']).rich_color)
        if 'jotline-cursor-background' in theme.variables:
            cursor = Color.parse(theme.variables['jotline-cursor-background'])
        self.register_theme(TextAreaTheme(
            self.THEME_NAME,
            cursor_style=Style(color=background.rich_color, bgcolor=cursor.rich_color),
            selection_style=selection,
            syntax_styles=syntax_styles(theme),
        ))

    def _app_theme_changed(self) -> None:
        self._register_markdown_theme()
        super()._app_theme_changed()

    def set_markdown_options(self, *, highlighting: bool, smart_lists: bool) -> None:
        self.smart_lists = smart_lists
        if highlighting != self.markdown_highlighting:
            self.markdown_highlighting = highlighting
            self._build_highlight_map()
            self.refresh()

    def edit(self, edit: Edit):
        self._pending_edit = edit
        try:
            return super().edit(edit)
        finally:
            self._pending_edit = None

    def _build_highlight_map(self) -> None:
        self._line_cache.clear()
        highlights = self._highlights
        lines = self.document.lines
        if not self.markdown_highlighting or sum(len(line) for line in lines) > HIGHLIGHT_MAX_CHARS:
            highlights.clear()
            self._fenced = None
            return
        edit = self._pending_edit
        if edit is None or self._fenced is None or not self._rehighlight_edit(edit, lines):
            highlights.clear()
            self._fenced = fenced_rows(lines)
            self._fence_markers = {row for row, line in enumerate(lines) if FENCE.fullmatch(line)}
            highlights.update(highlight_markdown(lines, self._fenced))

    def _rehighlight_edit(self, edit: Edit, lines: list[str]) -> bool:
        """Rescan only the rows ``edit`` touched; False when fence state may have changed."""
        if edit._edit_result is None:
            return False
        top, bottom = edit.top[0], edit.bottom[0]
        end = edit._edit_result.end_location[0]
        if (any(row in self._fence_markers for row in range(top, bottom + 1))
                or any(FENCE.fullmatch(lines[row]) for row in range(top, end + 1))):
            return False
        # No fence line was added or removed, so rows outside the edit keep
        # their state and the edited rows share the state of the first one.
        inside = top in self._fenced
        delta = end - bottom
        highlights = self._highlights
        if delta:
            def shift(rows):
                return {row + delta if row > bottom else row: rows[row] for row in rows if row < top or row > bottom}
            moved = shift(highlights)
            highlights.clear()
            highlights.update(moved)
            self._fenced = {row + delta if row > bottom else row for row in self._fenced
                            if row < top or row > bottom}
            self._fence_markers = {row + delta if row > bottom else row for row in self._fence_markers
                                   if row < top or row > bottom}
        for row in range(top, end + 1):
            line = lines[row]
            if inside:
                self._fenced.add(row)
                spans = highlight_fenced(line)
            else:
                spans = highlight_line(line) if line else []
            if spans:
                highlights[row] = spans
            else:
                highlights.pop(row, None)
        return True

    def check_consume_key(self, key: str, character: str | None = None) -> bool:
        if not self.read_only and self.tab_behavior == "indent" and key == "shift+tab":
            return True
        return super().check_consume_key(key, character)

    async def _on_key(self, event: events.Key) -> None:
        if not self.read_only and self.tab_behavior == "indent" and event.key in ("tab", "shift+tab"):
            row, _ = self.cursor_location
            if (event.key == "shift+tab" or not self.selection.is_empty
                    or list_item(self.document.get_line(row))):
                event.stop()
                event.prevent_default()
                self._restart_blink()
                self.apply_format("outdent" if event.key == "shift+tab" else "indent")
                return
        if event.key == "enter" and not self.read_only and self.selection.is_empty:
            row, column = self.cursor_location
            line = self.document.get_line(row)
            action = continuation(line, column) if self.smart_lists else None
            if action:
                fenced = self._fenced if self._fenced is not None else fenced_rows(self.document.lines[:row + 1])
                if row not in fenced:
                    event.stop()
                    event.prevent_default()
                    self._restart_blink()
                    prefix, clear = action
                    if clear:
                        self._replace_via_keyboard("", (row, 0), (row, len(line)))
                    else:
                        self._replace_via_keyboard("\n" + prefix, (row, column), (row, column))
                    return
            prefix = line[:column]
            indentation = prefix[:len(prefix) - len(prefix.lstrip(" \t"))]
            if indentation:
                event.stop()
                event.prevent_default()
                self._restart_blink()
                self._replace_via_keyboard("\n" + indentation, (row, column), (row, column))
                return
        await super()._on_key(event)

    def char_offset(self, location: tuple[int, int], text: str | None = None) -> int:
        """Character offset in the editor's text for a (row, column) location."""
        row, column = location
        text = self.text if text is None else text
        newline = self.document.newline
        lines = text.split(newline)
        return sum(len(line) + len(newline) for line in lines[:row]) + column

    def location_at(self, offset: int, text: str | None = None) -> tuple[int, int]:
        text = self.text if text is None else text
        newline = self.document.newline
        before = text[:offset]
        row = before.count(newline)
        return row, len(before.rsplit(newline, 1)[-1])

    def insert_checked(self, body: str, limit: int = EDIT_LIMIT_BYTES) -> bool:
        """Replace the selection, or insert at the cursor, as one undo step within the size limit."""
        text = self.text
        start, end = sorted((self.selection.start, self.selection.end))
        begin, finish = self.char_offset(start, text), self.char_offset(end, text)
        result_bytes = (len(text[:begin].encode("utf-8")) + len(body.encode("utf-8"))
                        + len(text[finish:].encode("utf-8")))
        if result_bytes > limit:
            return False
        self.history.checkpoint()
        self.replace(body, start, end)
        self.move_cursor(self.location_at(begin + len(body), self.text))
        self.history.checkpoint()
        return True

    def replace_checked(self, body: str, limit: int = EDIT_LIMIT_BYTES) -> bool:
        if len(body.encode("utf-8")) > limit:
            return False
        position = self.cursor_location
        self.history.checkpoint()
        self.replace(body, (0, 0), self.location_at(len(self.text), self.text))
        self.history.checkpoint()
        self.move_cursor(position)
        return True

    def select_match(self, query: str, *, reverse: bool = False,
                     anchor: int | None = None, case_sensitive: bool = False) -> tuple[int, int] | None:
        text = self.text
        if not query:
            return None
        if anchor is None:
            start, end = sorted((self.selection.start, self.selection.end))
            location = start if reverse else end
            anchor = self.char_offset(location, text)
        first = last = candidate = None
        first_ordinal = last_ordinal = candidate_ordinal = 0
        total = 0
        for total, match in enumerate(re.finditer(re.escape(query), text, 0 if case_sensitive else re.IGNORECASE), start=1):
            if first is None:
                first, first_ordinal = match, total
            last, last_ordinal = match, total
            if (reverse and match.start() < anchor) or (not reverse and match.start() >= anchor):
                if reverse:
                    candidate, candidate_ordinal = match, total
                elif candidate is None:
                    candidate, candidate_ordinal = match, total
        if first is None:
            return None
        if candidate is None:
            match, ordinal = (last, last_ordinal) if reverse else (first, first_ordinal)
        else:
            match, ordinal = candidate, candidate_ordinal
        start = self.location_at(match.start(), text)
        end = self.location_at(match.end(), text)
        self.move_cursor(start)
        self.move_cursor(end, select=True, center=True)
        return ordinal, total

    def toggle_task_line(self) -> None:
        """Check, uncheck, or create a task on the current line using the canonical task pattern."""
        row, _ = self.cursor_location
        line = self.document.get_line(row)
        if match := TASK.fullmatch(line):
            updated, _ = set_done(line + "\n", 1, match["mark"] == " ")
            self.replace(updated.splitlines()[0], (row, 0), (row, len(line)))
            return
        updated = toggle_lines([line], "task")[0]
        self.replace(updated, (row, 0), (row, len(line)))

    BLOCK_STYLES = {"heading": "h2", "list": "bullet", "numbered": "numbered", "task": "task", "quote": "quote",
                    **{f"h{level}": f"h{level}" for level in range(1, 7)}}
    WRAP_MARKERS = {"bold": "**", "italic": "*", "strike": "~~", "code": "`"}

    def apply_format(self, style: str) -> str | None:
        start, end = sorted((self.selection.start, self.selection.end))
        self.history.checkpoint()
        result = None
        if style in self.BLOCK_STYLES:
            self.transform_rows(start, end, lambda lines: toggle_lines(lines, self.BLOCK_STYLES[style]))
        elif style in ("indent", "outdent"):
            self.transform_rows(start, end, lambda lines: indent_lines(lines, outdent=style == "outdent"))
        elif style in self.WRAP_MARKERS:
            self.wrap_selection(style, start, end)
        elif style in ("link", "image"):
            self.insert_link(style == "image", start, end)
        elif style == "codeblock":
            self.format_code_block(start, end)
        elif style == "rule":
            self.insert_rule(end[0])
        elif style == "table":
            result = self.format_table_at_cursor()
        self.history.checkpoint()
        return result

    def selected_rows(self, start: tuple[int, int], end: tuple[int, int]) -> tuple[int, int]:
        first, last = start[0], end[0]
        if end[1] == 0 and last > first:
            last -= 1
        return first, last

    def transform_rows(self, start: tuple[int, int], end: tuple[int, int],
                       transform) -> None:
        first, last = self.selected_rows(start, end)
        lines = self.document.lines[first:last + 1]
        updated = transform(lines)
        self.replace("\n".join(updated), (first, 0), (last, len(lines[-1])))

        def shifted(location: tuple[int, int]) -> tuple[int, int]:
            row, column = location
            if first <= row <= last:
                index = row - first
                column = min(max(0, column + len(updated[index]) - len(lines[index])), len(updated[index]))
            return row, column

        self.move_cursor(shifted(start))
        if start != end:
            self.move_cursor(shifted(end), select=True)

    def select_offsets(self, begin: int, finish: int) -> None:
        text = self.text
        self.move_cursor(self.location_at(begin, text))
        self.move_cursor(self.location_at(finish, text), select=True)

    def wrap_selection(self, style: str, start: tuple[int, int], end: tuple[int, int]) -> None:
        text = self.text
        begin, finish = self.char_offset(start, text), self.char_offset(end, text)
        body = text[begin:finish]
        marker = self.WRAP_MARKERS[style]
        if body and (unwrapped := unwrap_span(style, text, begin, finish)):
            outer_begin, outer_finish, inner = unwrapped
            self.replace(inner, self.location_at(outer_begin, text), self.location_at(outer_finish, text))
            self.select_offsets(outer_begin, outer_begin + len(inner))
            return
        body = body or "text"
        padding = ""
        if style == "code":
            marker = "`" * (max((len(m[0]) for m in re.finditer(r"`+", body)), default=0) + 1)
            padding = " " if body.startswith("`") or body.endswith("`") else ""
        self.replace(marker + padding + body + padding + marker, start, end)
        inner = begin + len(marker + padding)
        self.select_offsets(inner, inner + len(body))

    def insert_link(self, image: bool, start: tuple[int, int], end: tuple[int, int]) -> None:
        text = self.text
        begin = self.char_offset(start, text)
        body = self.selected_text
        bang = "!" if image else ""
        url = body[1:-1] if body[:1] == "<" and body[-1:] == ">" else body
        if re.fullmatch(r"(?:https?|mailto):\S+", url):
            label = "alt text" if image else "text"
            self.replace(f"{bang}[{label}]({url})", start, end)
            self.select_offsets(begin + len(bang) + 1, begin + len(bang) + 1 + len(label))
            return
        label = " ".join(body.splitlines()) or ("alt text" if image else "text")
        target = "path" if image else "url"
        self.replace(f"{bang}[{label}]({target})", start, end)
        target_start = begin + len(bang) + len(label) + 3
        self.select_offsets(target_start, target_start + len(target))

    def insert_rule(self, row: int) -> None:
        lines = self.document.lines
        line = lines[row]
        below_blank = row + 1 < len(lines) and not lines[row + 1].strip()
        if line.strip():
            self.insert("\n\n---" + ("" if below_blank else "\n"), (row, len(line)))
            rule_row = row + 2
        else:
            above_blank = row == 0 or not lines[row - 1].strip()
            self.replace(("" if above_blank else "\n") + "---" + ("" if below_blank else "\n"),
                         (row, 0), (row, len(line)))
            rule_row = row + (0 if above_blank else 1)
        self.move_cursor((rule_row + 1, 0))

    def format_code_block(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        rows = self.document.lines
        first, last = self.selected_rows(start, end)
        opener = FENCE.fullmatch(rows[first])
        if (end[1] == 0 and end[0] > first and opener and closes_fence(rows[end[0]], opener)
                and not any(closes_fence(rows[row], opener) for row in range(first + 1, end[0]))):
            last = end[0]
        lines = rows[first:last + 1]
        if last > first and opener and closes_fence(lines[-1], opener):
            inner = lines[1:-1]
            self.replace("\n".join(inner), (first, 0), (last, len(lines[-1])))
            self.move_cursor((first, 0))
            if inner:
                self.move_cursor((first + len(inner) - 1, len(inner[-1])), select=True)
            return
        if start == end and not lines[0].strip():
            self.replace("```\n\n```", (first, 0), (first, len(lines[0])))
            self.move_cursor((first + 1, 0))
            return
        fence = fence_for("\n".join(lines))
        self.replace("\n".join([fence, *lines, fence]), (first, 0), (last, len(lines[-1])))
        self.move_cursor((first + 1, 0))
        self.move_cursor((last + 1, len(lines[-1])), select=True)

    def format_table_at_cursor(self) -> str | None:
        row, column = self.cursor_location
        lines = self.document.lines
        if bounds := table_bounds(lines, row):
            first, last = bounds
            original = lines[first:last + 1]
            tidy = format_table(original)
            self.replace("\n".join(tidy), (first, 0), (last, len(original[-1])))
            self.move_cursor((row, min(column, len(tidy[row - first]))))
            return "tidied"
        line = lines[row]
        template = "\n".join(TABLE_TEMPLATE)
        if line.strip():
            self.insert("\n\n" + template + "\n", (row, len(line)))
            top = row + 2
        else:
            self.replace(template, (row, 0), (row, len(line)))
            top = row
        self.move_cursor((top, 2))
        self.move_cursor((top, 8), select=True)
        return None
