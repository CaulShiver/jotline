"""Check the installed wheel, with Python isolated from the source checkout."""
import asyncio
from dataclasses import replace
import faulthandler
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

import jotline
from jotline.app import Jotline, MarkdownPreview
from jotline.action_history import ActionHistory
from jotline.action_ui import ActionEditor
from jotline.importing import apply_import, preview_import
from jotline.navigation import ViewEditor
from jotline.store import Vault
from textual.widgets import TextArea

SMOKE_TIMEOUT_SECONDS = int(os.environ.get("JOTLINE_SMOKE_TIMEOUT_SECONDS", "45"))
SUBPROCESS_TIMEOUT_SECONDS = int(os.environ.get("JOTLINE_SMOKE_SUBPROCESS_TIMEOUT_SECONDS", "10"))
INTERACTION_TIMEOUT_SECONDS = int(os.environ.get("JOTLINE_SMOKE_INTERACTION_TIMEOUT_SECONDS", "5"))


def progress(message: str) -> None:
    print(f"[smoke] {message}", file=sys.stderr, flush=True)


def run(
    command: list[str],
    label: str,
    *,
    capture_output: bool = True,
    timeout: int = SUBPROCESS_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    progress(label)
    return subprocess.run(command, text=True, capture_output=capture_output, check=True, timeout=timeout)


async def interact(label: str, awaitable):
    progress(label)
    return await asyncio.wait_for(awaitable, timeout=INTERACTION_TIMEOUT_SECONDS)


def start_watchdog() -> None:
    def watchdog() -> None:
        time.sleep(SMOKE_TIMEOUT_SECONDS)
        print(f"[smoke] hard timeout after {SMOKE_TIMEOUT_SECONDS}s", file=sys.stderr, flush=True)
        faulthandler.dump_traceback(file=sys.stderr)
        os._exit(124)

    threading.Thread(target=watchdog, daemon=True).start()


def check_installed_package_origin() -> None:
    package_path = Path(jotline.__file__).resolve()
    source_root = Path(__file__).resolve().parents[1] / "src"
    if source_root in package_path.parents:
        raise AssertionError(f"jotline imported from source checkout instead of installed wheel: {package_path}")


async def check_tui(directory: str, *, hard_exit: bool = False) -> None:
    check_installed_package_origin()
    command = [sys.executable, '-I', '-m', 'jotline', '--vault', directory]
    progress('TUI workflow: start')
    app = Jotline(Vault(Path(directory)))
    progress('TUI workflow: app constructed')
    async with app.run_test(size=(100, 30)) as pilot:
        progress('TUI workflow: run_test entered')
        await interact('TUI ready', pilot.pause())
        await interact('type first note', pilot.press('w', 'h', 'e', 'e', 'l'))
        await interact('new note hotkey', pilot.press('ctrl+n'))
        assert any(n.body == 'wheel' for n in app.vault.notes())
        assert app.query_one('#editor', TextArea).text == ''
        progress('workspace and tags')
        app.switch_workspace('work')
        app.query_one('#editor', TextArea).insert('Workspace smoke')
        app.add_tags('#release')
        assert app.vault.tags('work') == {'release': 1}
        assert not app.vault.tags('default')
        progress('custom hotkey for new note')
        app.save_settings(replace(app.settings, hotkeys={'new': 'f2'}))
        original = app.current.id
        await interact('press f2', pilot.press('f2'))
        assert app.current.id != original
        progress('format and preview command')
        app.command('format:bold')
        assert app.query_one('#editor', TextArea).text == '**text**'
        app.command('preview')
        await interact('preview opens', pilot.pause())
        assert isinstance(app.screen, MarkdownPreview)
        await interact('close preview', pilot.press('escape'))
        progress('templates and history')
        app.save_template('smoke-template')
        app.use_template('smoke-template')
        assert app.current.body == '**text**'
        assert app.vault.history(app.current.id)
        progress('custom preview hotkey')
        app.save_settings(replace(app.settings, hotkeys={'preview': 'f3', 'format_bold': 'f4'}))
        await interact('press f3', pilot.press('f3'))
        assert isinstance(app.screen, MarkdownPreview)
        await interact('close preview after f3', pilot.press('escape'))
        progress('action builder and recorded execution')
        app.command('action-builder')
        await interact('action builder opens', pilot.pause())
        assert isinstance(app.screen, ActionEditor)
        await interact('cancel action builder', pilot.press('escape'))
        app.save_settings(replace(app.settings, actions={'smoke-upper': [{'type': 'uppercase'}]}))
        app.run_local_action('smoke-upper')
        assert app.query_one('#editor', TextArea).text == '**TEXT**'
        assert ActionHistory(app.vault.path).read()[-1]['status'] == 'completed'
        app.command('filters')
        await interact('filter form opens', pilot.pause())
        assert isinstance(app.screen, ViewEditor)
        await interact('cancel filters', pilot.press('escape'))
        with tempfile.TemporaryDirectory() as source_folder:
            # macOS exposes its temp directory through the /var symlink. This
            # fixture owns that directory; pass its canonical path so the import
            # test exercises a regular file rather than the forbidden alias.
            source = Path(source_folder).resolve() / 'import.md'
            source.write_text('Installed import smoke', encoding='utf-8')
            plan = preview_import(app.vault, source, workspace='work')
            assert plan.ready == 1
            imported = apply_import(app.vault, plan)
            assert not imported.errors and len(imported.imported) == 1
            assert app.vault.read(imported.imported[0]).body == 'Installed import smoke'
        backup = run(command + ['backup'], 'CLI backup')
        assert Path(backup.stdout.strip()).is_file()
        await interact('final TUI pause', pilot.pause())
        await interact('quit app', pilot.press('ctrl+q'))
    progress('TUI workflow: complete')
    if hard_exit:
        os._exit(0)


def check(directory: str) -> None:
    check_installed_package_origin()
    progress(f'vault directory: {directory}')
    command = [sys.executable, '-I', '-m', 'jotline', '--vault', directory]
    captured = run(command + ['capture', 'Installed package smoke test'], 'CLI capture')
    exported = run(command + ['export', captured.stdout.strip()], 'CLI export')
    assert exported.stdout == 'Installed package smoke test'
    desktop = run(command + ['desktop', 'status', '--json'], 'CLI desktop status')
    report = json.loads(desktop.stdout)
    assert report['recipes'] == ['omarchy', 'hyprland', 'gnome', 'kde', 'pipe']
    recipe = run(command + ['desktop', 'recipe', 'hyprland'], 'CLI desktop recipe')
    assert 'org.jotline.capture' in recipe.stdout
    assert 'desktop launch' in recipe.stdout
    run(
        [sys.executable, '-I', str(Path(__file__).resolve()), '--tui-child', directory],
        'TUI child workflow',
        capture_output=False,
        timeout=SMOKE_TIMEOUT_SECONDS + 5,
    )
    print('Installed wheel: CLI capture/export, writing, tags, workspaces, hotkeys, Markdown, templates, backups, actions, filters and import passed.')


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == '--tui-child':
        start_watchdog()
        try:
            asyncio.run(asyncio.wait_for(check_tui(sys.argv[2], hard_exit=True), timeout=SMOKE_TIMEOUT_SECONDS))
        except asyncio.TimeoutError:
            sys.exit(f'Installed wheel TUI smoke timed out after {SMOKE_TIMEOUT_SECONDS}s')
        return
    if len(sys.argv) != 1:
        sys.exit('usage: smoke_install.py')
    with tempfile.TemporaryDirectory() as directory:
        progress(f'starting installed-wheel smoke with {SMOKE_TIMEOUT_SECONDS}s timeout')
        check(directory)


if __name__ == '__main__':
    main()
