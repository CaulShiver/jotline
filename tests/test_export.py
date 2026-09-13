"""HTML, Word and PDF exports from the shell and the app."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from jotline.app import Jotline, TextPrompt
from jotline.export import (ExportError, export_bytes, find_browser, find_office, format_for, render_html,
                            write_export)
from jotline.store import Vault

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="uses shell-script stand-ins for converters")


def run_cli(vault: Path, *args) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([sys.executable, "-m", "jotline", "--vault", os.fsencode(vault), *args],
                          capture_output=True, check=False, timeout=60)


def saved(vault: Vault, body: str, note_id: str):
    note = vault.new(body)
    note.id = note_id
    vault.save(note)
    return note


def test_html_is_self_contained_and_shows_raw_html_as_text():
    body = ("# Plan\n\n- [ ] call [[abc|Sam]]\n- [x] done [[def]]\n\n<script>alert(1)</script>\n\n"
            "![logo](https://example.com/x.png) [bad](javascript:alert(1))\n\n"
            "```\n- [ ] kept [[raw]]\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
    page = render_html("A <b> title", body, {"def": "Other note"})
    assert "<title>A &lt;b&gt; title</title>" in page
    assert "☐ call Sam" in page and "☒ done Other note" in page
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "<img" not in page and '<a href="https://example.com/x.png">logo</a>' in page
    assert 'href="javascript' not in page
    assert "- [ ] kept [[raw]]" in page
    assert "<table>" in page
    assert "default-src 'none'" in page


def test_format_is_guessed_from_the_output_name():
    assert format_for(None, Path("plan.DOCX")) == "docx"
    assert format_for(None, Path("plan.pdf")) == "pdf"
    assert format_for(None, Path("plan")) == "markdown"
    assert format_for(None, None) == "markdown"
    assert format_for("html", Path("plan.pdf")) == "html"


def test_write_export_never_replaces_a_file_without_force(tmp_path):
    target = tmp_path / "out.html"
    write_export(target, b"one")
    with pytest.raises(ExportError, match="already exists; pass --force"):
        write_export(target, b"two")
    assert target.read_bytes() == b"one"
    write_export(target, b"two", force=True)
    assert target.read_bytes() == b"two"
    with pytest.raises(ExportError, match="Folder does not exist"):
        write_export(tmp_path / "missing" / "out.pdf", b"x")
    with pytest.raises(ExportError, match="is a folder"):
        write_export(tmp_path, b"x")
    assert [path.name for path in tmp_path.iterdir()] == ["out.html"]


def stand_in(folder: Path, name: str, script: str) -> None:
    path = folder / name
    path.write_text("#!/bin/sh\n" + script)
    path.chmod(0o755)


@posix_only
def test_missing_converters_say_what_to_install(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(ExportError, match="Word export needs pandoc or LibreOffice"):
        export_bytes("Plan", "body", "docx")
    with pytest.raises(ExportError, match="PDF export needs Chromium"):
        export_bytes("Plan", "body", "pdf")


@posix_only
def test_a_failing_converter_falls_back_to_the_next(tmp_path, monkeypatch):
    stand_in(tmp_path, "chromium", "echo 'no display' >&2\nexit 3\n")
    stand_in(tmp_path, "soffice", 'while [ $# -gt 0 ]; do [ "$1" = --outdir ] && out=$2; shift; done\n'
                                  '/bin/mkdir -p "$out"\nprintf "%%PDF-stand-in" > "$out/note.pdf"\n')
    monkeypatch.setenv("PATH", str(tmp_path))
    assert export_bytes("Plan", "body", "pdf") == b"%PDF-stand-in"

    stand_in(tmp_path, "soffice", "echo 'profile locked' >&2\nexit 1\n")
    with pytest.raises(ExportError) as caught:
        export_bytes("Plan", "body", "pdf")
    assert "chromium: no display" in str(caught.value)
    assert "LibreOffice: profile locked" in str(caught.value)


def test_cli_exports_html_to_stdout_or_a_file(tmp_path):
    vault = Vault(tmp_path / "vault")
    saved(vault, "# Plan\n\n- [ ] call", "abcdef0123456789")
    page = run_cli(vault.path, "export", "abcd", "--format", "html")
    assert page.returncode == 0, page.stderr
    assert b"<h1>Plan</h1>" in page.stdout

    target = tmp_path / "plan.html"
    written = run_cli(vault.path, "export", "abcd", "-o", str(target))
    assert written.returncode == 0, written.stderr
    assert written.stdout.decode().strip() == str(target)
    assert "☐ call" in target.read_text(encoding="utf-8")
    again = run_cli(vault.path, "export", "abcd", "-o", str(target))
    assert again.returncode == 1
    assert "already exists; pass --force to replace it" in again.stderr.decode()
    assert run_cli(vault.path, "export", "abcd", "-o", str(target), "--force").returncode == 0

    markdown = tmp_path / "plan.md"
    assert run_cli(vault.path, "export", "abcd", "--output", str(markdown)).returncode == 0
    assert markdown.read_bytes() == b"# Plan\n\n- [ ] call"

    word = run_cli(vault.path, "export", "abcd", "--format", "docx")
    assert word.returncode == 1
    assert "Word export needs --output FILE" in word.stderr.decode()


@pytest.mark.skipif(not (find_browser() or find_office()), reason="needs Chromium, Chrome, Edge or LibreOffice")
def test_real_pdf_export(tmp_path):
    assert export_bytes("Plan", "# Plan\n\n- [ ] call Sam", "pdf").startswith(b"%PDF")


@pytest.mark.skipif(not (shutil.which("pandoc") or find_office()), reason="needs pandoc or LibreOffice")
def test_real_word_export(tmp_path):
    # A .docx file is a ZIP archive.
    assert export_bytes("Plan", "# Plan\n\n- [ ] call Sam", "docx").startswith(b"PK")


async def test_app_suggests_a_file_name_and_exports_in_the_background(tmp_path):
    vault = Vault(tmp_path / "vault")
    note = saved(vault, "# Weekly plan: Sam/Alex\n\nhello", "abcdef0123456789")
    app = Jotline(vault)
    async with app.run_test() as pilot:
        app.load_id(note.id)
        app.prompt_export("pdf")
        await pilot.pause()
        assert isinstance(app.screen, TextPrompt)
        assert app.screen.value.endswith("Weekly plan SamAlex.pdf")
        app.screen.dismiss(None)
        await pilot.pause()
        target = tmp_path / "plan.html"
        app.export_current("html", str(target))
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "<h1>Weekly plan: Sam/Alex</h1>" in target.read_text(encoding="utf-8")
