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


WHEEL_PLACEHOLDER = "jotline-<version>-py3-none-any.whl"
PINNED_WHEEL = re.compile(r"jotline-\d+\.\d+\.\d+-py3-none-any\.whl")


def test_install_docs_use_github_releases_not_pypi():
    readme = (ROOT / "README.md").read_text()
    install = (ROOT / "docs/install.md").read_text()

    for text in (readme, install):
        assert "https://github.com/CaulShiver/jotline/releases/latest" in text
        assert WHEEL_PLACEHOLDER in text
        assert PINNED_WHEEL.search(text) is None

    assert "not on PyPI" in readme
    assert re.search(r"not published\s+on PyPI", install)
    assert "Do not run `pip install jotline`" in install


def test_readme_identifies_caulshiver_jotline_and_first_run():
    readme = (ROOT / "README.md").read_text()
    heading, rest = readme.split("\n", 1)
    intro = rest.split("## Install", 1)[0]
    template = ROOT / "docs/terminal-reports/TEMPLATE.md"

    assert heading.strip() == "# ›_ jotline"
    assert "CaulShiver/jotline" in intro
    assert "https://github.com/CaulShiver/jotline" in intro
    assert "## 30-second start" in intro
    assert intro.index("## 30-second start") < intro.index("Ctrl+N")
    assert f"Version {jotline.__version__}" in readme
    assert "docs/terminal-reports/TEMPLATE.md" in readme
    assert "uv tool install 'jotline[encryption]'" not in readme
    assert template.is_file()
    assert "not tested" in template.read_text()
