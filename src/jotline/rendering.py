"""The offline Markdown dialect shared by the terminal and HTML exports.

Footnotes are parsed by markdown-it's maintained plugin, then lowered to the
ordinary tokens understood by both renderers. No note text is interpreted as
HTML, fetched, or used as a generated footnote ID.
"""
from __future__ import annotations

import html
import re

from markdown_it import MarkdownIt
from markdown_it.rules_core import StateCore
from markdown_it.token import Token
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.footnote.index import footnote_def, footnote_ref
from textual.widgets import Markdown


_FOOTNOTE_LABEL = re.compile(r"\[\^[^\s\[\]]{1,200}\]")


def _bounded_footnote_ref(state, silent):
    # The upstream rule scans until the next closing bracket for every [^.
    # Nested unmatched prefixes can therefore be quadratic. A bounded label
    # grammar rejects those before entering the plugin's otherwise useful rule.
    if _FOOTNOTE_LABEL.match(state.src, state.pos, state.posMax) is None:
        return False
    return footnote_ref(state, silent, always_match=False)


def _bounded_footnote_def(state, start_line, end_line, silent):
    start = state.bMarks[start_line] + state.tShift[start_line]
    if _FOOTNOTE_LABEL.match(state.src, start, state.eMarks[start_line]) is None:
        return False
    return footnote_def(state, start_line, end_line, silent)


def _text(content: str) -> Token:
    token = Token("text", "", 0)
    token.content = content
    return token


def _link(label: str, href: str, *, ident: str | None = None, title: str = "") -> list[Token]:
    opening = Token("link_open", "a", 1)
    opening.attrSet("href", href)
    if ident:
        opening.attrSet("id", ident)
    if title:
        opening.attrSet("title", title)
    return [opening, _text(label), Token("link_close", "a", -1)]


def _reference_id(token: Token) -> str:
    suffix = f"-{token.meta['subId'] + 1}" if token.meta.get("subId", 0) else ""
    return f"jl-footnote-ref-{token.meta['id'] + 1}{suffix}"


def _extract_image_references(children: list[Token]) -> tuple[list[Token], list[Token]]:
    kept, references = [], []
    for token in children:
        if token.type == "footnote_ref":
            references.append(token)
        else:
            if token.children:
                token.children, nested = _extract_image_references(token.children)
                references.extend(nested)
            kept.append(token)
    return kept, references


def _inline_footnotes(children: list[Token]) -> list[Token]:
    result = []
    for child in children:
        if child.type == "footnote_ref":
            number = child.meta["id"] + 1
            result.extend(_link(f"[{number}]", f"#jl-footnote-{number}",
                                ident=_reference_id(child), title=f"Footnote {number}"))
        else:
            if child.type == "image" and child.children:
                # An image's alternative text is flattened by both renderers.
                # Put any parsed references beside the image link instead of
                # hiding their IDs inside an alt label and breaking backlinks.
                child.children, references = _extract_image_references(child.children)
                result.append(child)
                result.extend(_inline_footnotes(references))
                continue
            elif child.children:
                child.children = _inline_footnotes(child.children)
            result.append(child)
    return result


def _reachable_footnotes(state: StateCore) -> None:
    """Discard refs in omitted/overwritten definitions before assigning IDs.

    The plugin parses every definition before it knows which ones are used.
    Recount only the retained document, then visit its reachable definitions
    once. A queue, not recursive expansion, also handles cyclic references.
    """
    main: list[Token] = []
    definitions: dict[int, tuple[Token, list[Token]]] = {}
    current: list[Token] | None = None
    for token in state.tokens:
        if token.type in {"footnote_block_open", "footnote_block_close", "footnote_anchor"}:
            continue
        if token.type == "footnote_open":
            current = []
            definitions[token.meta["id"]] = (token, current)
        elif token.type == "footnote_close":
            current = None
        else:
            (main if current is None else current).append(token)
    if not definitions:
        return

    order: list[int] = []
    numbers: dict[int, int] = {}
    counts: dict[int, int] = {}

    def collect(tokens: list[Token]) -> None:
        for token in tokens:
            if token.type == "footnote_ref":
                old = token.meta["id"]
                if old not in definitions:
                    token.type, token.content = "text", f"[^{token.meta.get('label', '')}]"
                    continue
                if old not in numbers:
                    numbers[old] = len(order)
                    counts[old] = 0
                    order.append(old)
                token.meta = {**token.meta, "id": numbers[old], "subId": counts[old]}
                counts[old] += 1
            if token.children:
                collect(token.children)

    collect(main)
    # Iteration deliberately includes newly discovered definitions appended
    # while reading another definition, without revisiting cycles.
    for old in order:
        collect(definitions[old][1])
    result = main
    if order:
        result.append(Token("footnote_block_open", "", 1))
        for old in order:
            opening, content = definitions[old]
            opening.meta = {**opening.meta, "id": numbers[old]}
            result.append(opening)
            result.extend(content)
            closing = result.pop() if content and content[-1].type == "paragraph_close" else None
            for occurrence in range(counts[old]):
                backlink = Token("footnote_anchor", "", 0)
                backlink.meta = {"id": numbers[old], "subId": occurrence}
                result.append(backlink)
            if closing is not None:
                result.append(closing)
            result.append(Token("footnote_close", "", -1))
        result.append(Token("footnote_block_close", "", -1))
    state.tokens = result


def _lower_footnotes(state: StateCore) -> None:
    """Use normal lists and links, rather than unsupported terminal token types."""
    result: list[Token] = []
    for token in state.tokens:
        if token.children:
            token.children = _inline_footnotes(token.children)
        if token.type == "footnote_block_open":
            separator = Token("hr", "hr", 0)
            separator.block = True
            separator.attrSet("class", "footnotes-sep")
            result.append(separator)
            token.type, token.tag = "ordered_list_open", "ol"
            token.attrSet("class", "footnotes")
        elif token.type == "footnote_block_close":
            token.type, token.tag = "ordered_list_close", "ol"
        elif token.type == "footnote_open":
            number = token.meta["id"] + 1
            token.type, token.tag = "list_item_open", "li"
            token.info = str(number)
            token.attrSet("id", f"jl-footnote-{number}")
        elif token.type == "footnote_close":
            token.type, token.tag = "list_item_close", "li"
        elif token.type == "footnote_anchor":
            number = token.meta["id"] + 1
            occurrence = token.meta.get("subId", 0) + 1
            back = [_text(" "), *_link("↩" if occurrence == 1 else f"↩{occurrence}",
                    f"#{_reference_id(token)}", title=f"Back to reference {occurrence} of footnote {number}")]
            # The plugin places backlinks before a final paragraph_close, or
            # after a non-paragraph block. Create a paragraph in the latter
            # case; Textual requires inline tokens to have a containing block.
            if result and result[-1].type == "inline":
                if result[-1].children is None:
                    result[-1].children = []
                result[-1].children.extend(back)
            elif len(result) >= 2 and result[-2].meta.get("jotline_backlinks"):
                result[-2].children.extend(back)
            else:
                opening = Token("paragraph_open", "p", 1)
                opening.block = True
                inline = Token("inline", "", 0)
                inline.children = back
                inline.meta["jotline_backlinks"] = True
                closing = Token("paragraph_close", "p", -1)
                closing.block = True
                result.extend([opening, inline, closing])
            continue
        result.append(token)
    for index, token in enumerate(result[:-1]):
        if token.type == "list_item_open" and (ident := token.attrGet("id")):
            # Textual composes list-item contents without mounting the item
            # wrapper itself. Its first content block is the scroll target.
            result[index + 1].meta["jotline_anchor"] = ident
    state.tokens = result


def _heading_ids(state: StateCore) -> None:
    from .headings import add_heading_ids

    add_heading_ids(state.tokens)


def _image_as_link(self, tokens, index, options, env):
    # A self-contained export must not read local images or contact servers.
    token = tokens[index]
    source = token.attrGet("src") or ""
    label = self.renderInlineAsText(token.children or [], options, env) or source
    return f'<a href="{html.escape(source)}">{html.escape(label)}</a>'


def markdown_parser() -> MarkdownIt:
    """Build a fresh, deterministic parser with no network-dependent features."""
    parser = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])
    # Named definitions only: undefined refs remain literal. Inline ^[notes]
    # are deliberately not part of Jotline's portable Markdown dialect.
    parser.use(footnote_plugin, inline=False, always_match_refs=False)
    parser.inline.ruler.at("footnote_ref", _bounded_footnote_ref)
    parser.block.ruler.at("footnote_def", _bounded_footnote_def,
                          {"alt": ["paragraph", "reference"]})
    parser.core.ruler.after("footnote_tail", "jotline_reachable_footnotes", _reachable_footnotes)
    parser.core.ruler.after("jotline_reachable_footnotes", "jotline_footnotes", _lower_footnotes)
    parser.core.ruler.after("jotline_footnotes", "jotline_heading_ids", _heading_ids)
    parser.add_render_rule("image", _image_as_link)
    return parser


def footnote_choices(body: str) -> list[tuple[str, str]]:
    """Keyboard destinations for the preview Contents palette.

    One definition/return pair per footnote avoids a huge palette from many
    repeated inline references. Pointer backlinks still reach each occurrence.
    """
    choices = []
    for token in markdown_parser().parse(body):
        if token.type == "list_item_open" and (ident := token.attrGet("id")):
            if ident.startswith("jl-footnote-"):
                number = token.meta["id"] + 1
                choices.extend([(ident, f"Footnote {number}"),
                                (f"jl-footnote-ref-{number}", f"Return to footnote {number} reference")])
    return choices


class PreviewMarkdown(Markdown):
    """Render the same tokens as export and navigate only local anchors.

    Textual has its own generated widget IDs. Keep the document's anchor IDs
    in the source tokens instead, avoiding CSS selectors made from note text.
    """

    def __init__(self, markdown: str | None = None, **kwargs):
        kwargs.setdefault("parser_factory", markdown_parser)
        kwargs.setdefault("open_links", False)
        super().__init__(markdown, **kwargs)

    def goto_anchor(self, anchor: str) -> bool:
        """Scroll to an already URL-decoded heading, footnote or reference."""
        def contains(block) -> bool:
            token = block._token
            inline = block._inline_token
            if token.attrGet("id") == anchor or token.meta.get("jotline_anchor") == anchor or (
                    inline is not None and any(child.attrGet("id") == anchor for child in inline.children or [])):
                return True
            # Tables retain their cell token tree but render it as one widget;
            # a backlink to a cell scrolls the enclosing table into view.
            return any(contains(child) for child in block._blocks)

        for block in self.query("MarkdownBlock"):
            if contains(block):
                block.scroll_visible(top=True)
                return True
        return False
