"""A synthetic shared corpus pins the offline preview/export Markdown contract."""
from html.parser import HTMLParser
import os
from pathlib import Path
import subprocess
import sys

import pytest
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll

from jotline.export import printable_markdown, render_html
from jotline.rendering import PreviewMarkdown, footnote_choices, markdown_parser


CORPUS = Path(__file__).with_name("fixtures") / "markdown_dialect.md"


class Document(HTMLParser):
    def __init__(self, source: str):
        super().__init__()
        self.ids = []
        self.links = []
        self.tags = []
        self.text = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a":
            self.links.append(attrs.get("href", ""))

    def handle_data(self, data):
        self.text.append(data)


def test_shared_corpus_is_offline_and_preserves_the_documented_dialect():
    body = CORPUS.read_text(encoding="utf-8")
    page = render_html("Synthetic corpus", body)
    document = Document(page)
    text = "".join(document.text)
    assert "table" in document.tags and "s" in document.tags
    assert "☐ Unfinished task" in text and "☒ Finished task" in text
    assert "Chosen duplicate body with formatting and café." in text
    assert "Superseded duplicate body" not in text
    assert "Unreferenced definitions" not in text
    assert "Unicode definition with emphasis." in text
    assert "[^missing]" in text and "An inline [^β] stays literal too." in text
    assert "- [ ] Fenced task stays literal" in text
    assert "[^β]: Fenced definition stays literal" in text
    assert "script" not in document.tags and "img" not in document.tags
    assert '<script>alert("not executable")</script>' in text
    assert not any(href.lower().startswith(("javascript:", "vbscript:")) for href in document.links)
    assert "https://example.invalid/reference" in document.links
    assert "default-src 'none'" in page
    assert len(document.ids) == len(set(document.ids))
    assert all(link[1:] in document.ids for link in document.links if link.startswith("#"))


def test_numbering_follows_references_and_every_occurrence_has_a_backlink():
    source = "B[^β] A[^a] B[^β].\n\n[^a]: Alpha.\n\n[^β]: Beta."
    parser = markdown_parser()
    output = parser.render(source)
    assert parser.render(source) == output
    assert output.index("Beta.") < output.index("Alpha.")
    document = Document(output)
    assert document.links.count("#jl-footnote-1") == 2
    assert document.links.count("#jl-footnote-2") == 1
    assert "#jl-footnote-ref-1-2" in document.links
    assert all(link[1:] in document.ids for link in document.links)


def test_reachable_definition_order_and_cycles_keep_real_backlink_targets():
    source = "[^a]: A, see [^b].\n\nMain[^a].\n\n[^b]: B, see [^a]."
    output = markdown_parser().render(source)
    document = Document(output)
    assert 'Main<a href="#jl-footnote-1"' in output
    assert output.index("A, see") < output.index("B, see")
    assert len(document.ids) == len(set(document.ids))
    assert all(link[1:] in document.ids for link in document.links)
    assert footnote_choices(source) == [
        ("jl-footnote-1", "Footnote 1"), ("jl-footnote-ref-1", "Return to footnote 1 reference"),
        ("jl-footnote-2", "Footnote 2"), ("jl-footnote-ref-2", "Return to footnote 2 reference")]


@pytest.mark.parametrize("label", ["café", "引用", 'a\"onmouseover=\"x', "a<b", "a&b", "../x", "β"])
def test_labels_are_never_interpolated_into_ids_or_attributes(label):
    output = markdown_parser().render(f"Here[^{label}].\n\n[^{label}]: Body.")
    document = Document(output)
    assert document.ids == ["jl-footnote-ref-1", "jl-footnote-1"]
    assert document.tags == ["p", "a", "hr", "ol", "li", "p", "a"]


def test_undefined_and_inline_notes_are_literal_and_labels_are_case_sensitive():
    output = markdown_parser().render("[^a] [^A] [^none] ^[inline]\n\n[^a]: lower\n\n[^A]: UPPER")
    assert "[^none] ^[inline]" in output
    assert 'href="#jl-footnote-1"' in output and 'href="#jl-footnote-2"' in output
    assert "lower" in output and "UPPER" in output


@pytest.mark.parametrize("definition", ["", "Body.", "\n    ```\n    code\n    ```",
                                         "\n    - list\n    - items", "\n    > quote"])
def test_nonparagraph_and_empty_definitions_have_balanced_standard_tokens(definition):
    tokens = markdown_parser().parse(f"Here[^a] and again[^a].\n\n[^a]: {definition}")
    nesting = 0
    for token in tokens:
        assert not token.type.startswith("footnote_")
        nesting += token.nesting
        assert nesting >= 0
    assert nesting == 0
    document = Document(markdown_parser().renderer.render(tokens, markdown_parser().options, {}))
    assert all(link[1:] in document.ids for link in document.links)


def test_image_alternative_footnotes_keep_visible_references_and_valid_backlinks():
    output = markdown_parser().render("![alt[^a]](https://example.invalid/image)\n\n[^a]: Body.")
    document = Document(output)
    assert "img" not in document.tags
    assert 'href="https://example.invalid/image">alt</a><a href="#jl-footnote-1"' in output
    assert all(link[1:] in document.ids for link in document.links if link.startswith("#"))


class PreviewApp(App):
    def __init__(self, body):
        super().__init__()
        self.body = body

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield PreviewMarkdown(self.body)


async def test_preview_renders_corpus_and_navigates_references_and_backlinks(monkeypatch):
    source = printable_markdown(CORPUS.read_text(encoding="utf-8"), followable=True)
    app = PreviewApp(source)
    async with app.run_test() as pilot:
        await pilot.pause()
        preview = app.query_one(PreviewMarkdown)
        text = " ".join(block._content.plain for block in preview.query("MarkdownBlock"))
        assert "Chosen duplicate body with formatting and café." in text
        assert "Unicode definition with emphasis." in text
        assert "[^missing]" in text and "[1]" in text and "↩2" in text
        assert len(preview.query("MarkdownTable")) == 1
        assert len(preview.query("MarkdownFence")) == 1
        targets = []
        for block in preview.query("MarkdownBlock"):
            monkeypatch.setattr(block, "scroll_visible", lambda block=block, **kwargs: targets.append(block))
        assert preview.goto_anchor("jl-footnote-1")
        assert targets[-1]._token.meta["jotline_anchor"] == "jl-footnote-1"
        assert preview.goto_anchor("jl-footnote-ref-1-2")
        assert any(token.attrGet("id") == "jl-footnote-ref-1-2" for token in targets[-1]._inline_token.children)
        assert preview.goto_anchor("jl-footnote-ref-2-2")
        assert targets[-1]._token.type == "table_open"
        assert not preview.goto_anchor("not-a-real-anchor")
        assert not preview.goto_anchor("\"] [onclick]")


@pytest.mark.parametrize("definition", ["", "\n    ```\n    code\n    ```", "\n    - one\n    - two"])
async def test_preview_accepts_empty_and_block_footnotes(definition):
    app = PreviewApp(f"Here[^a] and again[^a].\n\n[^a]: {definition}")
    async with app.run_test() as pilot:
        await pilot.pause()
        preview = app.query_one(PreviewMarkdown)
        assert preview.goto_anchor("jl-footnote-1")
        assert preview.goto_anchor("jl-footnote-ref-1-2")


@pytest.mark.parametrize("kind", ["unmatched", "long-labels", "repeated"])
def test_adversarial_footnotes_finish_in_a_bounded_subprocess(kind):
    program = r'''
import sys
from jotline.rendering import markdown_parser
kind = sys.argv[1]
if kind == "unmatched":
    body = "[^" * 10_000 + "\n\n[^x]: definition"
elif kind == "long-labels":
    body = ("[^" + "a" * 201 + "] ") * 1_000 + "\n\n[^x]: definition"
else:
    body = "[^x] " * 10_000 + "\n\n[^x]: definition"
markdown_parser().render(body)
'''
    environment = os.environ.copy()
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, [source_root, environment.get("PYTHONPATH")]))
    result = subprocess.run([sys.executable, "-c", program, kind], capture_output=True, text=True,
                            timeout=5, check=False, env=environment)
    assert result.returncode == 0, result.stderr
