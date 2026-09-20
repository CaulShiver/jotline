"""Reproduce outliner research observations using synthetic text only.

Run from the repository root with:
    .venv/bin/python exa-results/jotline-outliner-2026-09-19/probes.py
Writes observations.json beside this file. This is a diagnostic harness, not
a regression test asserting the current bugs are correct behavior.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace

from markdown_it import MarkdownIt
from textual.widgets import Tree
import jotline.outliner as model
import jotline.outliner_ui as ui

Outline = model.Outline

def structure(outline):
    return [
        {"content": b.content,
         "parent": b.parent.content.splitlines()[0] if b.parent else None}
        for b in outline.walk()
    ]

def markdown_structure(text):
    return [
        {"type": t.type, "level": t.level, "lines": t.map}
        for t in MarkdownIt("commonmark").parse(text)
        if t.type in ("list_item_open", "paragraph_open", "code_block", "fence")
    ]

def correctness():
    parent_text = "- Parent\n  - Child\n\n  Parent paragraph\n- Other"
    o = Outline(parent_text)
    before = structure(o)
    child = o.roots[0].children[0]
    o.siblings(child).remove(child)
    results = {
        "parent_ownership": {
            "input": parent_text, "outline_before": before,
            "markdown_structure": markdown_structure(parent_text),
            "after_child_delete": o.text,
            "parent_paragraph_survives": "Parent paragraph" in o.text,
        }
    }
    for name, body in {
        "ordered_indent": "10. Parent\n  - Is this a child?\n11. Next",
        "indented_code": "    - literal code\n\n- Real item",
    }.items():
        o = Outline(body)
        results[name] = {
            "input": body, "byte_roundtrip": o.text == body,
            "outline": structure(o), "markdown_structure": markdown_structure(body),
        }
    for name, content in {
        "multiline_marker": "Parent\n- continuation",
        "unfinished_fence": "```\ntext",
    }.items():
        o = Outline("- Parent\n  - Child\n- Other")
        o.roots[0].set_content(content)
        saved = o.text
        results[name] = {
            "serialized": saved, "before_reload": structure(o),
            "after_reload": structure(Outline(saved)),
            "markdown_structure": markdown_structure(saved),
            "same_structure_after_reload": structure(o) == structure(Outline(saved)),
        }
    return results

class Source:
    def __init__(self, text):
        self.text = text

    def location_at(self, *args):
        return (0, 0)

    def replace(self, *args):
        pass

class SyncProbe:
    # Execute the real method, stubbing only downstream buffer and app work.
    sync = ui.OutlinerScreen.sync

    def __init__(self, body, outline):
        self.source = Source(body)
        self.outline = outline
        self.app = SimpleNamespace(capture_current_buffer=lambda: None)

def median_ms(function, repeats):
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        function()
        samples.append((time.perf_counter() - start) * 1000)
    return round(statistics.median(samples), 2)

def benchmarks():
    rows = []
    for count in (100, 1000, 5000, 10000):
        body = "\n".join(f"- Item {i:05d} " + "detail " * 8 for i in range(count))
        o = Outline(body)
        o.roots[count // 2].set_content("changed text")
        probe = SyncProbe(body, o)

        def make_tree():
            tree = Tree("Note")
            for block in o.roots:
                tree.root.add(block.content, block, allow_expand=False)

        probe.sync()  # Warm up interpreter specialization.
        rows.append({
            "blocks": count,
            "bytes": len(body.encode("utf-8")),
            "parse_median_ms_7_runs": median_ms(lambda: Outline(body), 7),
            "sync_preparation_median_ms_11_runs": median_ms(probe.sync, 11),
            "unmounted_tree_build_median_ms_3_runs": median_ms(make_tree, 3),
        })
    return rows

result = {
    "date": "2026-09-19",
    "environment": {
        "python": sys.version,
        "platform": platform.platform(),
        "packages": {name: importlib.metadata.version(name)
                     for name in ("textual", "markdown-it-py")},
        "source_sha256": {
            Path(m.__file__).name: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
            for m in (model, ui)
        },
    },
    "method": {
        "data": "Synthetic flat outlines, 70 ASCII characters per line including separator.",
        "sync": "Actual OutlinerScreen.sync, with source.location_at, source.replace and app.capture_current_buffer stubbed. Measures serialization, equality, UTF-8 size check, prefix/suffix scan and slicing. Excludes actual editor mutation, rendering, event delivery, filesystem I/O and autosave.",
        "tree": "Build an unmounted Textual Tree of leaf nodes. Excludes screen layout, actual OutlinerScreen.rebuild labels and painting.",
        "caveat": "Single-machine microbenchmarks, not end-to-end latency or user-study results.",
    },
    "correctness": correctness(),
    "benchmarks": benchmarks(),
}
destination = Path(__file__).with_name("observations.json")
destination.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({"observations": str(destination), "benchmarks": result["benchmarks"]}, indent=2))
