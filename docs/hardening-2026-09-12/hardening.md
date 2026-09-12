# Security Hardening Review: Jotline

## Evidence Basis

I inspected the editing, search, save/recovery, and local-action paths against
baseline `c66497ba4d01cda4403533b5136f6131fe8bda07`. Baseline evidence hashes are
recorded in [context.md](context.md); the derived assessment is in
[hardening.json](hardening.json). The earlier red-team report supplies historical
context, not proof about this revision. This was a focused reliability and
usability pass, not a complete security audit.

Three regressions reproduced against the baseline:

| Evidence | Observed behavior | Implemented repair |
| --- | --- | --- |
| Find/replace and editing helpers (E001, E002) | An oversized single replacement leaves text unchanged but advances selection and reports success. | Editing helpers return success explicitly; rejection keeps the selected match and displays “Not replaced.” Replace-all rejection also shows persistent inline feedback. |
| Find navigation (E001) | Selecting a match from right to left makes previous/next search repeat it. | Order selection endpoints before choosing the search anchor; empty queries leave selection unchanged. |
| Query compilation (E003) | Compact dates pass date validation but compare incorrectly against hyphenated metadata dates. | Require canonical calendar dates and preserve inclusive boundaries and the `today` keyword. |

## Constraints

We prioritize correct edits and clear feedback while preserving the existing
offline storage model, conflict checks, size limits, and undo behavior. All
execution used synthetic temporary vaults. No note migration or dependency
change is necessary. Compact dates in saved queries must be rewritten as
`YYYY-MM-DD`; they now receive the existing format error instead of silently
producing misleading results.

## Opportunity Portfolio

No structural security opportunity qualified from this evidence. We can address
the demonstrated failures at their existing editing and query boundaries.
Introducing new storage or isolation architecture would not explain or resolve
these particular failures more directly.

## Recommendation Summary

I recommend these local repairs. The editor already owns size enforcement;
returning its result lets the caller report the actual outcome. Canonical date
validation makes accepted input compatible with the existing date comparison.
Neither change requires a new service, persistent state, or migration mechanism.
Performance effects were not benchmarked; the added checks use constant-size
selection endpoints and date strings.

Verification completed on Linux:

- Baseline suite: 238 passed, 3 skipped.
- New regressions before fixes: 3 failed, 3 passed, reproducing each issue.
- Expanded final suite: 254 passed, 3 platform-specific skips.
- Fresh installed-wheel smoke: CLI capture/export, terminal editing, workspaces,
  tags, custom hotkeys, Markdown, templates, history workflow, and backup passed.
- Whitespace validation: `git diff --check` passed.

The added tests exercise rejected edits, backward selection, empty queries,
literal replacement with undo, all four date filters, and inclusive boundaries.
Reverting the focused source changes rolls back behavior without changing notes.

## Next Decisions

No further decision is required for these local fixes. Native macOS and Windows
execution remains for cross-platform CI. Broader security assurance would require
a separately scoped review; these results do not establish coverage of every
filesystem or concurrency boundary.
