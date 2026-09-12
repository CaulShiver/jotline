# Changelog

## 0.9.0 — 2026-09-12

- Added an action builder, starter recipes, result previews, action editing and
  duplication, recipe sharing, and bounded action run history.
- Added visible navigation controls, contextual empty states, and an optional
  quick-start guide that preserves the current note.
- Added saved-view editing, renaming, duplication and updates, filter controls,
  and an active-view indicator.
- Added recovery comparison with explicit preservation of the full local draft
  before reviewing an external version.
- Added folder and Drafts JSON export import with preview, metadata mapping,
  duplicate handling and partial-result summaries.
- Added versioned release packages with checksums and a cross-platform test gate,
  installation/update/uninstall instructions, and contributor templates.
- Added private vulnerability reporting, a security policy, a public roadmap,
  and a terminal/accessibility testing checklist.
- Corrected replacement failure feedback, backward selection search navigation,
  and canonical date-filter validation.
- Restored Tab/Shift+Tab navigation inside modals and removed a redundant
  Markdown preview render.

Existing notes and settings remain readable. Imports create new notes and do not
overwrite existing notes. Compact date filters must use `YYYY-MM-DD`. Local
action history is stored separately from note revision history.
Older releases do not recognize the new `quote` and `restore` recipe steps;
back up settings before downgrading, or remove those recipes using 0.9.0 first.

## 0.8.1 and earlier

The pre-release source history introduced Markdown capture, collections,
workspaces, tags, templates, history/backups, saved views, local JSON actions,
native Windows/macOS support and sidebar context menus. See the Git history and
[earlier review](docs/redteam-review.md) for the historical fixes. Version 0.9.0
is the first packaged GitHub release.
