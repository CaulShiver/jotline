# Local action recipes

Open the command palette and choose **Create action with step-by-step builder**. Name your action, select a step, choose its operation, and edit its value if needed. **Apply step** keeps that step's changes; **Add step**, **Remove**, **Up**, and **Down** arrange the recipe. Save and Preview also apply the currently selected step. Use Tab to move between controls, arrows to choose, Ctrl+S to save, and Escape to cancel. The dialog scrolls on small terminals.

**Use a built-in action recipe** starts from four configurable examples:

- **copy-clean-text** trims surrounding whitespace, copies the result, and restores the original source text.
- **copy-markdown-quote** prefixes every line (including blank lines) with a Markdown quote marker, copies the result, and restores the original source. Existing LF, CRLF and CR line endings are preserved.
- **create-from-template** renders the built-in meeting template into a new inbox note and preserves the source. Change `{{template:meeting}}` to another template or enter your own text.
- **append-and-archive** appends the source to a note and archives the source after a successful append. Use **Choose append target by title** to select a note in the current workspace. The placeholder must be replaced before saving.

**Edit, rename, duplicate or export action** opens existing recipes. Editing the name renames the action; duplicate creates an independent copy. Existing names cannot accidentally be overwritten. Running an action remains explicit: choose **Run local action**.

## Preview and execution

Preview renders templates and text transforms without saving notes, changing collections, appending, exporting, or touching the clipboard. It shows intended effects and their text, plus the final source text; each text excerpt is limited to 20,000 characters. Preview does not prove that targets, permissions, or conflict checks will succeed when the action runs. Date/time templates use the time of preview or execution.

Steps run in order. Uppercase, lowercase, trim, quote, template, and archive changes are staged until the final source save. Append, clipboard, and export effects happen immediately; a later failure cannot roll them back. A `restore` step resets the working text to the original source text, which is how copy/create starter recipes preserve their source. It does not undo prior effects or reset the collection.

Export creates a new inbox note in the terminal UI; the CLI action runner uses its configured output destination. Clipboard steps require the terminal UI. Action recipes cannot execute commands or make network requests.

## Troubleshooting

**View action run history** shows the latest 100 runs, with per-step completed, failed, and not-run statuses. A separate `save` step records whether the final source write succeeded. A completed text transform means the working text was transformed; if a later step failed, that text was not saved. Earlier append, copy, or export effects can remain applied after failure.

History is stored privately in `.jotline-action-history.json`, bounded to 256 KiB. It records action names, note IDs, workspace, timestamps, step types/statuses and exception classes. It does not store note bodies or recipe values. History-write failures are reported separately from execution outcomes. Existing runs before this feature have no history.

A `committed-with-warning` result means the source file was replaced, but the subsequent durability check failed. The editor shows the committed text; inspect the warning before rerunning an action that appends or exports, to avoid repeating those effects.

## Sharing

Use **Export shareable recipe** to create a new JSON file; existing files are never overwritten. Review template content and target IDs before sharing. **Import shared action recipes** adds validated recipes without executing them. Duplicate names are rejected; rename an existing action before importing a colliding name. After import, review each recipe with the builder, configure append targets for your vault, and preview it.

The versioned format is:

```json
{
  "format": "jotline-actions",
  "version": 1,
  "actions": {
    "copy-clean-text": [
      {"type": "strip"},
      {"type": "copy"},
      {"type": "restore"}
    ]
  }
}
```

Only `template` and `append` accept a string `value`. Template values accept `{{body}}`, `{{selection}}`, `{{title}}`, `{{date}}`, `{{workspace}}`, and existing template includes. Recipes allow 1–16 steps and settings allow 128 actions. Names use lowercase letters, digits, hyphens or underscores, up to 48 characters. File import is bounded and rejects symlinks, special files, unknown operations and malformed fields.

See [community examples](../examples/actions/README.md) for capture-preserving
copy/export recipes and inbox filing recipes. They use only built-in steps; there
is no plugin SDK. Replace `TARGET_NOTE_ID` before running an append recipe.
