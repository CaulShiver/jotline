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
- Install a versioned package without Git and share reproducible bug reports.

## Next priorities

1. Validate the release with newcomers on Linux and macOS. Measure
   whether they can install, capture, find, process and recover a note unaided.
   Windows support is deferred indefinitely.
2. Establish native terminal and assistive-technology coverage using
   [the terminal checklist](docs/terminal-testing.md).
3. Improve performance using representative synthetic vault benchmarks before
   introducing indexing or storage complexity.
4. Expand community recipes and migration fixtures based on real user workflows.

External executable actions, regex search, dictation, AI and plugin APIs need
separate designs and evidence of user demand. They are not required to capture
or process notes locally.

## Starter contributions

Each item can be proposed as a focused issue or PR:

| Task | Acceptance criteria |
| --- | --- |
| Document one terminal setup | Copy `docs/terminal-reports/TEMPLATE.md`, record Linux or macOS terminal versions, keyboard and clipboard behavior using the checklist; no personal notes ([#2](https://github.com/CaulShiver/jotline/issues/2) macOS, [#3](https://github.com/CaulShiver/jotline/issues/3)). |
| Add an example local action | Include a recipe, synthetic input/output, and a test; use supported built-in steps only. |
| Improve one confusing empty state | Describe the trigger, include before/after screenshots, and verify keyboard navigation. |
| Add a migration fixture | Provide a minimal synthetic export and verify metadata mapping and duplicate behavior. |
| Report a contrast or focus issue | Identify theme/control/terminal and provide a reproducible keyboard path. |

Discuss changes that alter note formats, shortcuts, or public APIs before
implementation. See [CONTRIBUTING.md](CONTRIBUTING.md).
