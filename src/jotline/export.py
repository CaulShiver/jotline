"""Standalone HTML, Word and PDF copies of a note.

HTML is rendered here. Word and PDF are converted from that HTML by tools that
are often already installed: a Chromium-based browser for PDF, pandoc for Word,
and LibreOffice for either. Nothing is uploaded anywhere.
"""
from __future__ import annotations

import html
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

from .links import rewrite_wiki_links, wiki_href
from .filesystem import link_unsupported, rename_noreplace
from .tasks import TASK, fenced_pairs

FORMATS = ("markdown", "html", "docx", "pdf")
FORMAT_NAMES = {"markdown": "Markdown", "html": "HTML", "docx": "Word", "pdf": "PDF"}
SUFFIXES = {".md": "markdown", ".markdown": "markdown", ".txt": "markdown", ".html": "html", ".htm": "html",
            ".docx": "docx", ".pdf": "pdf"}
EXTENSIONS = {"markdown": ".md", "html": ".html", "docx": ".docx", "pdf": ".pdf"}
BINARY = frozenset({"docx", "pdf"})
TIMEOUT_SECONDS = 180
# A browser prints a note in a few seconds; a longer wait means it is stuck, so
# move on to the next converter rather than hold the user for three minutes.
BROWSER_TIMEOUT_SECONDS = 30
# How long to keep watching for the PDF after a browser launcher exits cleanly.
EXIT_GRACE_SECONDS = 20
BROWSERS = ("chromium", "chromium-browser", "google-chrome-stable", "google-chrome", "chrome",
            "microsoft-edge-stable", "microsoft-edge", "msedge", "brave-browser", "brave")
PDF_ENGINES = ("weasyprint", "wkhtmltopdf", "typst", "tectonic", "xelatex", "lualatex", "pdflatex")
MISSING_TOOLS = {
    "docx": "Word export needs pandoc or LibreOffice; install one, or export HTML and open it in Word",
    "pdf": ("PDF export needs Chromium, Google Chrome, Microsoft Edge, LibreOffice, or pandoc with a PDF "
            "engine; install one, or export HTML and print it from a browser"),
}

STYLE = """
@page { margin: 2cm; }
body { font: 11pt/1.5 -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  color: #1d2327; max-width: 46rem; margin: 2rem auto; padding: 0 1rem; }
h1, h2, h3, h4 { line-height: 1.25; margin: 1.4em 0 .5em; }
h1 { font-size: 1.8em; } h2 { font-size: 1.4em; } h3 { font-size: 1.15em; }
p, ul, ol, pre, table, blockquote { margin: 0 0 1em; }
a { color: #1a5d8f; }
code, pre { font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace; font-size: .92em; }
pre { background: #f3f5f6; padding: .75em 1em; overflow-x: auto; white-space: pre-wrap; }
blockquote { border-left: 3px solid #c8d1d6; margin-left: 0; padding-left: 1em; color: #4a555c; }
table { border-collapse: collapse; } th, td { border: 1px solid #c8d1d6; padding: .3em .6em; text-align: left; }
hr { border: 0; border-top: 1px solid #c8d1d6; }
"""


class ExportError(ValueError):
    """An export could not be produced or written."""


def format_for(requested: str | None, output: Path | None) -> str:
    if requested:
        return requested
    if output is not None:
        return SUFFIXES.get(output.suffix.lower(), "markdown")
    return "markdown"


def printable_markdown(body: str, titles: dict[str, str] | None = None,
                       *, followable: bool = False) -> str:
    """Show checkboxes as ☐/☒ and wiki links as their labels, leaving fenced code alone.

    When followable, wiki links become ``[label](jotline:target)`` so preview
    can open the note without contacting a server. Exports keep plain labels.
    """
    titles = titles or {}

    pairs, fenced = fenced_pairs(body)
    result = []
    for row, (content, ending) in enumerate(pairs):
        if row not in fenced:
            if task := TASK.fullmatch(content):
                # ☒ has no emoji form, unlike ☑, so both boxes print in the text font.
                content = task["lead"][:-1] + ("☐ " if task["mark"] == " " else "☒ ") + task["text"]
        result.append(content + ending)
    rendered = "".join(result)

    def replace(link, match):
        label = link.label or titles.get(link.target, link.target)
        if followable:
            return f"[{label}]({wiki_href(link.target)})"
        return label

    return rewrite_wiki_links(rendered, replace)


def render_html(title: str, body: str, titles: dict[str, str] | None = None) -> str:
    """A self-contained page. Raw HTML in the note is shown as text and nothing is loaded from elsewhere."""
    from markdown_it import MarkdownIt

    renderer = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])

    def image(self, tokens, index, options, env):
        # Images become links: an export must not read local files or contact servers.
        token = tokens[index]
        source = token.attrGet("src") or ""
        label = self.renderInlineAsText(token.children or [], options, env) or source
        return f'<a href="{html.escape(source)}">{html.escape(label)}</a>'

    renderer.add_render_rule("image", image)
    content = renderer.render(printable_markdown(body, titles))
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">\n"
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{html.escape(title)}</title>\n<style>{STYLE}</style>\n</head>\n<body>\n{content}</body>\n</html>\n")


def _existing(*candidates: str) -> str | None:
    return next((candidate for candidate in candidates if candidate and Path(candidate).is_file()), None)


def find_browsers() -> list[str]:
    """Every installed Chromium-based browser, best first, without duplicates.

    More than one is tried because one can be broken where another works: a
    Chromium build without a usable sandbox next to a packaged Google Chrome.
    """
    found: list[str] = []
    seen: set[str] = set()

    def add(path: str | None) -> None:
        if path and (key := os.path.realpath(path)) not in seen:
            seen.add(key)
            found.append(path)

    for name in BROWSERS:
        add(shutil.which(name))
    for candidate in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                      "/Applications/Chromium.app/Contents/MacOS/Chromium",
                      "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"):
        add(_existing(candidate))
    return found


def find_browser() -> str | None:
    browsers = find_browsers()
    return browsers[0] if browsers else None


def find_office() -> str | None:
    found = shutil.which("soffice") or shutil.which("libreoffice")
    return found or _existing("/Applications/LibreOffice.app/Contents/MacOS/soffice")


def _pdf_complete(output: Path) -> bool:
    """A PDF is finished once its trailer (%%EOF) has been written."""
    try:
        with open(output, "rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            if size < 8:
                return False
            stream.seek(max(0, size - 64))
            return b"%%EOF" in stream.read()
    except OSError:
        return False


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def _run(command: list[str], output: Path, timeout: float = TIMEOUT_SECONDS) -> str | None:
    """Run a converter; return why it failed, or None when it wrote the output.

    The PDF itself, not the process, decides when a browser is done. Chrome on
    macOS keeps helper processes alive after printing. Errors go to a file
    because a pipe nobody reads can fill and stall a chatty browser.
    """
    wants_pdf = output.suffix == ".pdf"
    with tempfile.TemporaryFile() as errors:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors)
        except OSError as error:
            return error.strerror or str(error)
        deadline = time.monotonic() + timeout
        exited_at = None
        settled = (-1, 0.0)  # (size, when first seen) of the output after a clean exit
        try:
            while True:
                if wants_pdf and _pdf_complete(output):
                    return None
                now = time.monotonic()
                if process.poll() is not None:
                    if not wants_pdf:
                        break
                    exited_at = exited_at or now
                    if process.returncode == 0:
                        # Some converters write a valid file without a trailing
                        # %%EOF; accept it once it has stopped growing.
                        size = output.stat().st_size if output.is_file() else 0
                        if size != settled[0]:
                            settled = (size, now)
                        elif size and now - settled[1] >= 0.5:
                            return None
                    # A clean exit may leave a child still printing; a crash rarely does.
                    if now - exited_at >= (EXIT_GRACE_SECONDS if process.returncode == 0 else 2):
                        break
                if now >= deadline:
                    _stop(process)
                    return None if wants_pdf and _pdf_complete(output) else f"timed out after {timeout:g} seconds"
                time.sleep(0.1)
        finally:
            _stop(process)
        if process.returncode == 0 and output.is_file() and output.stat().st_size and not wants_pdf:
            return None
        errors.seek(0)
        detail = errors.read()[-64 * 1024:].decode("utf-8", "replace").strip().splitlines()
    if detail:
        return detail[-1][:200]
    return f"exit status {process.returncode}" + (", no PDF written" if process.returncode == 0 else "")


def converters(fmt: str, page: Path, work: Path):
    """(tool name, output path, command, timeout) for each installed converter, best first."""
    target = work / ("out" + EXTENSIONS[fmt])
    office, pandoc = find_office(), shutil.which("pandoc")
    for index, browser in enumerate(find_browsers() if fmt == "pdf" else []):
        name = Path(browser).stem

        # Called inside this iteration, so the browser it reads is this one.
        def browser_command(profile: str, *extra: str) -> list[str]:  # noqa: B023
            # The mock keychain keeps macOS Chrome from waiting on a keychain
            # prompt a headless run can never answer. Each attempt gets its own
            # profile, because a crashed browser can leave a profile lock that
            # makes the next launch wait. Do not add --blink-settings=
            # scriptEnabled=false: headless Chrome then exits 0 without printing.
            # The page's CSP already blocks every script.
            return [browser, *extra, "--headless", "--disable-gpu",  # noqa: B023
                    "--no-first-run", "--no-default-browser-check",
                    "--disable-extensions", "--use-mock-keychain", "--password-store=basic",
                    f"--user-data-dir={work / profile}",
                    "--no-pdf-header-footer", "--print-to-pdf-no-header", f"--print-to-pdf={target}", page.as_uri()]

        yield name, target, browser_command(f"browser-{index}"), BROWSER_TIMEOUT_SECONDS
        if sys.platform.startswith("linux"):
            # Ubuntu 23.10 and later restrict the unprivileged user namespaces
            # the browser sandbox needs, and the browser crashes at start. The
            # page is generated here, loads nothing (its CSP forbids it) and runs
            # no script, so a retry without the sandbox is a contained fallback.
            yield (f"{name} without sandbox", target, browser_command(f"browser-{index}-unsandboxed", "--no-sandbox"),
                   BROWSER_TIMEOUT_SECONDS)
    if pandoc and fmt == "docx":
        yield "pandoc", target, [pandoc, "--from=html", "--to=docx", f"--output={target}", str(page)], TIMEOUT_SECONDS
    if pandoc and fmt == "pdf":
        for engine in PDF_ENGINES:
            if shutil.which(engine):
                yield f"pandoc ({engine})", target, [pandoc, "--from=html", f"--pdf-engine={engine}",
                                                     f"--output={target}", str(page)], TIMEOUT_SECONDS
                break
    if office:
        # A private profile keeps a running LibreOffice from swallowing the job.
        filters = {"docx": "docx:MS Word 2007 XML", "pdf": "pdf:writer_web_pdf_Export"}
        yield "LibreOffice", work / "office" / (page.stem + EXTENSIONS[fmt]), [
            office, "--headless", "--norestore", f"-env:UserInstallation={(work / 'office-profile').as_uri()}",
            "--convert-to", filters[fmt], "--outdir", str(work / "office"), str(page)], TIMEOUT_SECONDS


def export_bytes(title: str, body: str, fmt: str, titles: dict[str, str] | None = None) -> bytes:
    if fmt == "markdown":
        return body.encode("utf-8")
    page_text = render_html(title, body, titles)
    if fmt == "html":
        return page_text.encode("utf-8")
    with tempfile.TemporaryDirectory(prefix="jotline-export-", ignore_cleanup_errors=True) as folder:
        work = Path(folder)
        page = work / "note.html"
        page.write_text(page_text, encoding="utf-8")
        failures = []
        for tool, output, command, timeout in converters(fmt, page, work):
            # A failed attempt must not leave a partial file for the next converter to accept.
            output.unlink(missing_ok=True)
            problem = _run(command, output, timeout)
            if problem is None:
                return output.read_bytes()
            failures.append(f"{tool}: {problem}")
        if not failures:
            raise ExportError(MISSING_TOOLS[fmt])
        raise ExportError(f"{FORMAT_NAMES[fmt]} export failed ({'; '.join(failures)})")


def write_export(target: Path, data: bytes, *, force: bool = False) -> Path:
    """Write the whole file under a temporary name first; replace an existing file only with force."""
    target = target.expanduser()
    if target.is_dir():
        raise ExportError(f"{target} is a folder; name the file to write")
    if not target.parent.is_dir():
        raise ExportError(f"Folder does not exist: {target.parent}")
    exists = f"{target} already exists; pass --force to replace it"
    if not force and os.path.lexists(target):
        raise ExportError(exists)
    temporary = target.with_name(f".{target.name}.jotline-{uuid4().hex}")
    try:
        # Notes are 0600 and the key file is 0600; an export of an encrypted
        # note carries the same text in the clear, so it is created private
        # too rather than taking whatever the umask happens to allow.
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with open(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if force:
            os.replace(temporary, target)
        else:
            try:
                # A hard link publishes the file only if the name is still free.
                os.link(temporary, target)
            except FileExistsError:
                raise ExportError(exists) from None
            except OSError as error:
                if not link_unsupported(error):
                    raise
                try:
                    rename_noreplace(temporary, target)
                except FileExistsError:
                    raise ExportError(exists) from None
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return target


def suggested_name(title: str, fmt: str) -> str:
    stem = re.sub(r"[^\w\- ]+", "", title).strip()[:60].strip() or "note"
    return stem + EXTENSIONS[fmt]
