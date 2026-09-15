"""Packaging metadata regressions."""
from pathlib import Path
import re
import tomllib

import jotline


ROOT = Path(__file__).resolve().parents[1]


def test_version_is_single_sourced_from_package_init():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert data["project"]["dynamic"] == ["version"]
    assert "version" not in data["project"]
    assert data["tool"]["hatch"]["version"]["path"] == "src/jotline/__init__.py"
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:[a-z]+\d+)?", jotline.__version__)


def test_build_backend_and_runtime_dependency_bounds_are_explicit():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert data["build-system"]["requires"] == ["hatchling==1.32.0"]
    assert data["project"]["dependencies"] == ["textual>=8.2.8,<9"]
    assert data["project"]["optional-dependencies"]["dev"] == ["pytest>=8.2", "pytest-asyncio>=0.24"]
    assert data["project"]["urls"]["Repository"] == "https://github.com/CaulShiver/jotline"
    assert data["tool"]["pytest"]["ini_options"]["asyncio_default_fixture_loop_scope"] == "function"


def test_ci_gives_pytest_eight_minutes():
    workflow = (ROOT / ".github/workflows/test.yml").read_text()

    assert "      - name: Run tests\n        timeout-minutes: 8\n" in workflow
    assert "timeout-minutes: 15" in workflow


def test_install_docs_advertise_the_current_wheel():
    wheel = f"jotline-{jotline.__version__}-py3-none-any.whl"
    leftover = re.compile(r"jotline-0\.\d+\.\d+-py3-none-any\.whl")
    for path in (ROOT / "README.md", ROOT / "docs/install.md", ROOT / "docs/release-notes.md"):
        text = path.read_text()
        assert wheel in text, path.name
        assert leftover.findall(text.replace(wheel, "")) == []


def test_ci_lower_bound_pair_matches_pytest_asyncio_floor():
    workflow = (ROOT / ".github/workflows/test.yml").read_text()

    assert "'pytest==8.2.0'" in workflow
    assert "'pytest-asyncio==0.24.0'" in workflow
    assert "'pytest==8.0.0'" not in workflow
    assert "/tmp/jotline-lower-bound/bin/python -m pytest -q tests/test_cli_redteam.py tests/test_packaging.py" in workflow
    assert "uv venv .lower-bound" not in workflow
    assert "tests/test_storage_redteam.py tests/test_cli_redteam.py" not in workflow


def test_smoke_tui_success_path_allows_context_cleanup():
    smoke = (ROOT / "scripts/smoke_install.py").read_text()
    complete = smoke.index("progress('TUI workflow: complete')")
    exit_success = smoke.index("os._exit(0)")

    assert complete < exit_success
    assert "os._exit(124)" in smoke
    assert "await interact('quit app', pilot.press('ctrl+q'))" in smoke
    assert "    progress('TUI workflow: complete')\n    if hard_exit:\n        os._exit(0)" in smoke
