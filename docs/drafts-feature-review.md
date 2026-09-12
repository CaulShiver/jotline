# Drafts features that fit Jotline's terminal workflow

Reviewed September 12, 2026 against the Drafts user guide and Jotline's current
source (`app.py`, `store.py`, `cli.py`, `settings.py`, and `templates.py`).
The table records the gaps identified before implementation. Version 0.8 now
implements the initial terminal workflows in all nine areas: literal replacement
with case matching, headings and recent notes, snippet/link completion, saved
views and richer queries, line/paragraph arrangement, bulk operations, local
action recipes, CLI updates, and extended templates. See the README for usage.
Regex replacement, OR/tag-any logic, external executable actions, action groups
and run logs remain follow-up work. Effort below describes the original scope,
not a delivery estimate.

## What Jotline already covers

Jotline already has quick capture, autosave, inbox/archive/trash, stars, inline
tags, workspaces, daily logs, reusable note templates, note history, local ZIP
backups, Markdown formatting and preview, a command palette, customizable
shortcuts, note links/backlinks, and shell capture/import/export. Those should
not be counted as wholly missing Drafts features.

This change expands the selectable themes from nine to seventeen using palettes
already bundled with the minimum supported Textual version, 8.2.8. The additions
are Monokai, Flexoki, Catppuccin Latte/Frappé/Macchiato, and Rosé Pine/Moon/Dawn.

## Recommended additions

| Priority | Drafts capability and source | Current Jotline gap | Terminal implementation | Scope |
| --- | --- | --- | --- | --- |
| 1 | [Find and replace](https://docs.getdrafts.com/docs/editor/find): replacements, case matching, regex, and search history | `FindInNote` navigates literal matches but has no replacement interface | Add Replace and Replace all to the existing modal, with match counts and one undo operation. Start with literal replacement; make regex an explicit later option. | Small–medium |
| 2 | [Navigation](https://docs.getdrafts.com/docs/editor/navigation): headings and recently active drafts | Note/link pickers exist, but no heading outline or navigation history | Add **Jump to heading**, **Previous note**, and **Recent notes** to the palette; retain cursor positions. Parse Markdown headings while excluding fenced code. | Small–medium |
| 3 | [Autocomplete](https://docs.getdrafts.com/docs/editor/autocomplete): snippets, note links, and insertion of another draft's text | Templates create new notes; links require opening a palette | First add **Insert template at cursor** and **Insert note text**. Then offer suggestions after `[[` or a snippet trigger, operated with arrows and Enter. | Medium |
| 4 | [Search and organization](https://docs.getdrafts.com/drafts/): exact phrases and excluded terms; [workspaces](https://docs.getdrafts.com/docs/drafts/workspaces): saved queries, tag logic, date filters, sort and theme | Search splits whitespace and ANDs terms/tags. Workspaces are exclusive note membership, not saved filters; appearance is vault-wide | Introduce saved **views** within existing workspaces, preserving their meaning. Save query, collection, sort and optional theme; add phrase/exclusion queries and created/modified date filters. | Medium |
| 5 | [Arrange mode](https://docs.getdrafts.com/docs/editor/arrangemode): reorder lines, blocks, or sentences before applying | Formatting and task toggling exist, but there is no structured reordering tool | Add a modal list with move-up/down commands, duplicate, Apply and Cancel. Begin with lines and paragraphs; apply as one undoable editor change. | Medium |
| 6 | [Bulk operations](https://docs.getdrafts.com/drafts/): move, tag, flag, trash, and merge several drafts | Operations target the current note | Add keyboard multi-select and a selection count, then bulk tagging/archiving and merge into a new note. Keep source notes by default and report partial failures. | Medium–large |
| 7 | [Action steps](https://docs.getdrafts.com/actions/steps/) and [scripting](https://docs.getdrafts.com/docs/actions/scripting.html): composable text processing and integrations | The command registry is fixed Python code. Shell export/capture can be composed externally, but there are no user-defined in-app actions | Add named local actions runnable from the palette and CLI, starting with copy, append to note, export and text transforms. Add optional external executable steps after the built-in model is sound. | Large |
| 8 | [Automation URLs](https://docs.getdrafts.com/docs/automation/urlschemes): append, prepend, open and update existing drafts | CLI supports capture and export, but cannot generally append/prepend to a chosen note, open a note by ID, or list notes as JSON | Add `append NOTE_ID`, `prepend NOTE_ID`, `open NOTE_ID`, and `list --json`; accept piped UTF-8 input for updates. These are proposed command names. | Medium |
| 9 | [Action templates](https://docs.getdrafts.com/docs/actions/templates/drafts-templates): title/body/selection fields, formatted dates, reusable template includes | Templates substitute only date, time and workspace, mainly for new notes | Extend the current `{{...}}` syntax with title, selection, and date formatting, then output templates for actions. Keep existing templates compatible and bound recursive includes. | Medium |

## Suggested implementation sequence

Start with find/replace, heading navigation, and insertion of templates into the
current note. These improve daily writing without changing the storage model or
requiring external services. Each text transformation should preserve selection
where practical and be reversible with the editor's normal Undo command.

Next add richer search and saved views. Drafts' workspaces combine filters and
presentation settings; Jotline's workspaces assign each note to one context.
Replacing Jotline's model would change existing search and link behavior. Views
can provide the Drafts benefit without migrating workspace membership.

Then expand CLI automation and build local actions on those operations. A useful
first workflow is **append this thought to a project note, then archive the
source after the append succeeds**. Use the existing vault locking, conflict
detection and history paths for every write. Preview external-action output
before replacing a note; pass note text via stdin rather than interpolating it
into shell commands. Execution needs timeouts, output limits and clear errors.
Action groups and run logs can follow once individual actions are reliable.

## Features with a weaker immediate fit

Drafts also documents [dictation, scanning, speech and audio/video
transcription](https://docs.getdrafts.com/editor/), and [AI chat, an MCP server,
iCloud protection and Mail Drop](https://docs.getdrafts.com/). These are absent
from Jotline but introduce services, platform adapters, or substantial additional
infrastructure. Keep them optional if pursued. A terminal can accept text from
an external transcription tool through existing piped capture; microphone and
camera interfaces need separate integration work.

An MCP interface is feasible after stable query/update APIs exist, but it offers
less immediate writing value than the first three recommendations. Native Apple
Shortcuts, AppleScript, widgets and share extensions do not translate directly
to a cross-platform terminal app; CLI commands and user-triggered actions are
the more natural equivalents. This is a focused terminal-fit review, not a
complete parity specification for every Drafts integration.
