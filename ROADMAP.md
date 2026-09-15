# Jotline roadmap

Jotline aims to make capture, finding, processing and recovery understandable
without reading the entire README. New integrations remain user-triggered and
the writing core remains offline.

## Current milestone: everyday usability

- Configure and preview useful local actions without writing JSON.
- Discover collections, saved views and basic workflows in the app.
- Edit, rename and duplicate saved configurations.
- Resolve save conflicts while preserving both versions.
- Preview folder and Drafts imports, then report exactly what was imported.
- Install with a one-liner or PyPI (`uv tool install jotline`) without Git or
  hunting a GitHub wheel. Linux, macOS, and Windows stay in the contract.

## Next priorities

1. Validate the release with newcomers on Linux, macOS and Windows. Measure
   whether they can install, capture, find, connect, process and recover a note
   unaided.
2. Establish native terminal and assistive-technology coverage using
   [the terminal checklist](docs/terminal-testing.md).
3. Improve performance using representative synthetic vault benchmarks before
   introducing indexing or storage complexity.
4. Expand community recipes and migration fixtures based on real user workflows.

Connecting notes is a visible loop (connections panel, follow, and
create-from-broken-`[[link]]`). Attachments, unlinked mentions, and a graph
view stay parked until that panel is used daily.

External executable actions, regex search, dictation, AI and plugin APIs need
separate designs and evidence of user demand. They are not required to capture
or process notes locally.

## Starter contributions

Each item can be proposed as a focused issue or PR:

| Task | Acceptance criteria |
| --- | --- |
| Document one terminal setup | Record OS/terminal versions, keyboard and clipboard behavior using the checklist; no personal notes. |
| Add an example local action | Include a recipe, synthetic input/output, and a test; use supported built-in steps only. |
| Improve one confusing empty state | Describe the trigger, include before/after screenshots, and verify keyboard navigation. |
| Add a migration fixture | Provide a minimal synthetic export and verify metadata mapping and duplicate behavior. |
| Report a contrast or focus issue | Identify theme/control/terminal and provide a reproducible keyboard path. |

Discuss changes that alter note formats, shortcuts, or public APIs before
implementation. See [CONTRIBUTING.md](CONTRIBUTING.md).
