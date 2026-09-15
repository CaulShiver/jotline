"""Community recipes in examples/actions. Built-in steps only; no plugin SDK."""
from datetime import datetime
import json
from pathlib import Path

import pytest

from jotline.action_recipes import merge_recipes, read_recipes
from jotline.actions import run_action, validate_actions
from jotline.store import Vault


EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "actions"
TODAY = datetime.now().astimezone().date().isoformat()


def example_files() -> list[Path]:
    return sorted(EXAMPLES.glob("*.json"))


def load_all_actions() -> dict:
    merged = {}
    for path in example_files():
        merged = merge_recipes(merged, read_recipes(path))
    return merged


def saved(vault, body, **fields):
    note = vault.new(body)
    for name, value in fields.items():
        setattr(note, name, value)
    vault.save(note)
    return note


def with_target(steps, note_id: str):
    out = []
    for step in steps:
        if step.get("type") == "append":
            out.append({**step, "value": note_id})
        else:
            out.append(dict(step))
    return out


def test_example_files_parse_and_have_unique_names():
    files = example_files()
    assert {path.name for path in files} >= {"starter-recipes.json", "inbox-process.json"}
    names = []
    for path in files:
        actions = read_recipes(path)
        validate_actions(actions)
        names.extend(actions)
        for steps in actions.values():
            assert not any(step["type"] in {"shell", "command", "http"} for step in steps)
    assert len(names) == len(set(names))
    validate_actions(load_all_actions())


def test_readme_documents_every_example_recipe():
    readme = (EXAMPLES / "README.md").read_text()
    for name in load_all_actions():
        assert f"`{name}`" in readme


def test_starter_copy_and_export_recipes_preserve_source(tmp_path):
    vault = Vault(tmp_path)
    source = saved(vault, "  Call the dentist  ")
    actions = read_recipes(EXAMPLES / "starter-recipes.json")
    copies, exports = [], []
    for name in ("clean-copy", "quote-copy", "share-selection", "meeting-note",
                 "task-from-capture", "dated-journal", "weekly-review-seed"):
        result = run_action(vault, source, actions[name], selection="dentist",
                            copy=copies.append, export=exports.append)
        assert result.body == source.body == vault.read(source.id).body
        assert result.collection == "inbox"
    assert copies[0] == "Call the dentist"
    assert copies[1].startswith("> ")
    assert copies[2] == "dentist"
    assert exports[0].startswith("# Meeting")
    assert exports[1] == "- [ ] Call the dentist"
    assert exports[2] == f"# {TODAY}\n\n  Call the dentist  "
    assert exports[3].startswith("# Weekly review — ")
    assert "- [ ] Read unprocessed captures" in exports[3]


def test_inbox_process_files_and_archives(tmp_path):
    vault = Vault(tmp_path)
    source = saved(vault, "  Buy milk  ")
    target = saved(vault, "# Groceries\n")
    log = saved(vault, "# Daily log\n")
    actions = read_recipes(EXAMPLES / "inbox-process.json")

    filed = run_action(vault, source, with_target(actions["file-to-project"], target.id))
    assert filed.collection == "archive"
    assert vault.read(target.id).body.endswith("Buy milk")
    assert vault.read(source.id).body == "Buy milk"

    trimmed = saved(vault, "  leftover  ")
    result = run_action(vault, trimmed, actions["trim-and-archive"])
    assert result.body == "leftover" and result.collection == "archive"

    quote_source = saved(vault, "a thought")
    quoted = run_action(vault, quote_source, with_target(actions["quote-into-log"], log.id))
    assert quoted.body == "a thought" and quoted.collection == "inbox"
    logged = vault.read(log.id).body
    assert f"## Captured {TODAY}" in logged
    assert "> a thought" in logged


def test_placeholder_target_must_be_replaced_before_a_real_run(tmp_path):
    vault = Vault(tmp_path)
    source = saved(vault, "orphan")
    actions = read_recipes(EXAMPLES / "inbox-process.json")
    with pytest.raises((OSError, ValueError)):
        run_action(vault, source, actions["file-to-project"])


def test_importing_examples_does_not_overwrite(tmp_path):
    existing = {"clean-copy": [{"type": "uppercase"}]}
    incoming = read_recipes(EXAMPLES / "starter-recipes.json")
    with pytest.raises(ValueError, match="already exist"):
        merge_recipes(existing, incoming)


def test_examples_reject_a_plugin_or_shell_step(tmp_path):
    payload = {
        "format": "jotline-actions",
        "version": 1,
        "actions": {"hack": [{"type": "shell"}]},
    }
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        read_recipes(path)
