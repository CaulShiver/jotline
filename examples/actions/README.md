# Community action examples

These recipes use only built-in steps (no shell, network, or plugin SDK). Import
a JSON file with **Import shared action recipes**, then **Preview** before
**Run local action**. Duplicate names are refused; rename first.

| File | When you would use it |
| --- | --- |
| [starter-recipes.json](starter-recipes.json) | Copy or spawn a note without changing the capture |
| [inbox-process.json](inbox-process.json) | File a capture into another note and/or archive it |

Replace `TARGET_NOTE_ID` in inbox recipes with a real ID from this workspace
(**Choose append target by title** in the builder) before running.

## starter-recipes.json

| Name | What it does | Source note |
| --- | --- | --- |
| `clean-copy` | Trim surrounding whitespace, copy, restore | Unchanged |
| `quote-copy` | Prefix every line with `> `, copy, restore | Unchanged |
| `share-selection` | Copy the current selection only, restore | Unchanged |
| `meeting-note` | Render the built-in meeting template into a new inbox note | Unchanged |
| `task-from-capture` | Export `- [ ]` plus the capture body as a new inbox note | Unchanged |
| `dated-journal` | Export `# YYYY-MM-DD` plus the capture body | Unchanged |
| `weekly-review-seed` | Export a weekly-review checklist dated today | Unchanged |

Synthetic example for `task-from-capture`: body `Call the dentist` → exported note
`- [ ] Call the dentist`; the original capture still reads `Call the dentist`.

`share-selection` copies nothing when the selection is empty; select text first.

Clipboard steps need the terminal UI. `jotline run` cannot copy; use export recipes
from the CLI.

## inbox-process.json

| Name | What it does | Source note |
| --- | --- | --- |
| `file-to-project` | Append the capture to `TARGET_NOTE_ID`, then archive the source | Archived after a successful append |
| `trim-and-archive` | Trim surrounding whitespace and archive | Archived (trimmed text saved) |
| `quote-into-log` | Quote the capture, wrap with `## Captured YYYY-MM-DD`, append to the log, restore | Unchanged; the log grows |

Synthetic example for `file-to-project`: source `Buy milk`, target `# Groceries`
→ target ends with `Buy milk`, source collection becomes `archive`.

## Contributing

Add a version 1 `jotline-actions` JSON file. Describe the effect, required
template/target setup, and whether it changes the source. Include a concrete
input/output example in this README and a test in `tests/test_example_actions.py`.
Do not include personal note IDs, private text, credentials, shell commands,
network integrations, or a plugin SDK. Names must be unique across every file
in this folder; imports never replace existing actions.
