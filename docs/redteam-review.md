# Jotline multi-model review

Date: 2026-09-10. Baseline: `7253ab0` (0.2.0).

This was an engineering and security review of the complete small application,
using three independent model reviewers and an integrating reviewer. It was not
a penetration test of a hosted service; Jotline has no server or network service.

## Review coverage

| Reviewer | Focus |
| --- | --- |
| GPT-6 Astra | Markdown storage, settings, filesystem trust, concurrent writers, malformed input |
| GPT-5.6 Sol | Terminal UI, modal keyboard handling, save-state transitions, settings and workflows |
| GPT-5.6 Terra | CLI inputs/outputs, capture, packaging, diagnostics, performance |
| Integrating reviewer | Cross-process UI/CLI behavior, dependency audit, built-wheel testing, CI, regression review |

All reproductions used temporary synthetic vaults. No personal notes were used.

## Findings and remediation

The following reproduced issues were fixed in version 0.3.0.

- **Note loss through untracked edits:** link-related commands could copy a pending
  buffer into the in-memory note before the editor's change event ran, preventing
  the dirty flag from being set. Capture the buffer through one dirty-tracking path.
- **Commands running under modals:** global shortcuts could create a note or nest
  palettes while a picker was open. Make modal screens own their keyboard input.
- **Unsafe filesystem entries:** linked notes could read outside the vault, and
  named pipes could block vault loading. Use bounded reads from regular files,
  reject symlinks/special files, and use a bounded wait for the vault lock.
- **Malformed documents:** deeply nested JSON could crash settings or note loading.
  Convert malformed-input failures to actionable diagnostics and retain files.
- **Daily-capture concurrency:** the read and save were separate transactions.
  Perform the complete append while holding the vault lock.
- **Misleading workflow state:** the initial heading and sidebar could claim inbox
  while new notes went to another collection; startup focus settings applied mid-session.
  Keep the displayed collection accurate and distinguish startup preferences from
  current layout state.
- **Source-only test confidence:** CI did not honor the dependency lock and did not
  exercise the distributable wheel. Test locked dependencies, then install the wheel
  and run an isolated CLI/editor smoke test. Pin workflow actions to immutable commits.
- **Terminal-control output:** filenames in errors and note exports could contain
  terminal escape sequences. Escape diagnostics and require explicit raw output
  before emitting unsafe controls to an interactive terminal; preserve redirected
  export data.
- **Newline and save-retry edges:** text-mode reads normalized CRLF line endings,
  and a directory-sync failure after replacement could cause a false edit conflict
  on retry. Preserve exact source bytes when decoding and track the committed write.

## Workflow additions

- Find within the current note, with next/previous matches.
- Refresh the vault after external capture, keeping unfinished editor text.
- `jotline doctor` for content-free vault diagnostics and useful exit status.
- `jotline import FILE` for safe file capture without moving the source.
- An in-memory cache for unchanged notes, invalidated by file metadata changes and
  explicit refresh. Saving still reads the actual file before checking for conflicts.

## Dependency audit

`pip-audit` found no known published vulnerabilities in the 14 installed third-party
packages it audited. Jotline itself was skipped by that service because it is not a
PyPI package; its source was reviewed here. This is a point-in-time database check,
not a guarantee that dependencies contain no vulnerabilities.

## Verification

**All 64 tests passed locally.** The built-wheel smoke test also passed.

The review added regression coverage for storage failure modes, concurrent shell
capture, terminal output, dialogs, pending edits, refresh, in-note search, and cache
invalidation. An isolated installation of the built wheel also exercises capture,
export, and a terminal writing session independently of the source checkout.

A synthetic 1,000-note cache check measured 73.3 ms for the first search and 6.6 ms
on average across ten warm searches on the review machine. This is an illustrative
local measurement, not a cross-platform performance guarantee. Cache retention is
bounded at 2,048 notes and approximately 32 MiB; notes outside the cache remain
searchable. Directory scanning and query matching still run on every search.

## Limits

The vault is user-owned local storage, not a security boundary against a malicious
process running as the same user. Advisory locks coordinate Jotline instances;
external editors and synchronization tools do not participate in that protocol.
Terminal-specific clipboard and rendering behavior still depend on the terminal.
