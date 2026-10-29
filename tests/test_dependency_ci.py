"""Keep latest-allowed execution distinct from the reproducible locked baseline."""
from pathlib import Path
import re


WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def test_latest_dependencies_are_installed_and_executed_not_only_resolved():
    workflow = (WORKFLOWS / "dependency-compatibility.yml").read_text()
    install = workflow.index("uv sync --upgrade --extra dev --extra encryption")
    suite = workflow.index("uv run --locked pytest -q -o faulthandler_timeout=60")
    smoke = workflow.index(".smoke-venv/bin/python -I scripts/smoke_install.py")
    assert install < suite < smoke
    assert "uv pip install --python .smoke-venv/bin/python --upgrade --strict dist/*.whl" in workflow
    assert "--dry-run" not in workflow
    assert "continue-on-error" not in workflow
    assert "uv pip freeze --python .venv/bin/python" in workflow
    assert "git diff -- uv.lock > latest-lock.diff" in workflow
    assert "if: always()" in workflow
    assert "retention-days: 14" in workflow
    assert "persist-credentials: false" in workflow
    assert "contents: read" in workflow
    assert "contents: write" not in workflow


def test_latest_dependency_checks_have_bounded_matrix_and_recurring_cadence():
    workflow = (WORKFLOWS / "dependency-compatibility.yml").read_text()
    assert "schedule:" in workflow and "cron:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "pull_request:" in workflow and "push:" in workflow
    assert "branches: [main]" in workflow
    assert "'pyproject.toml'" in workflow and "'uv.lock'" in workflow
    assert "runs-on: ubuntu-latest" in workflow
    assert "python: ['3.11', '3.13']" in workflow
    assert "max-parallel: 2" in workflow
    assert "timeout-minutes: 25" in workflow
    # Workflow expressions stay outside shell interpolation except the trusted,
    # literal Python matrix values; actions remain immutable commit references.
    for action in re.findall(r"uses: ([^\s]+)", workflow):
        assert re.fullmatch(r"[\w/-]+@[0-9a-f]{40}", action), action


def test_full_supported_os_matrix_keeps_its_locked_baseline():
    workflow = (WORKFLOWS / "test.yml").read_text()
    assert "os: [ubuntu-latest, macos-latest]" in workflow
    assert "python: ['3.11', '3.12', '3.13']" in workflow
    assert "uv sync --locked --extra dev --extra encryption" in workflow
    assert "uv run --locked pytest -q" in workflow
    assert "uv sync --upgrade" not in workflow
    assert "uv lock --upgrade --dry-run" not in workflow
    assert "'markdown-it-py==4.0.0'" in workflow
    assert "'mdit-py-plugins==0.6.1'" in workflow
