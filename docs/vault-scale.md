# Vault scale: measure before indexing

Search and backlinks scan the workspace in memory. That is the right design for
a capture-first writing room until a measured vault misses the bar below. Do
not add SQLite, or another index, to feel serious.

## Bar

These times are for a cold `notes()` scan plus `search` / `backlinks` on a
synthetic vault of `{uuid}.md` files with ~40-word bodies and wiki-links to one
hub note. The machine should be idle; treat the numbers as a ceiling, not a
benchmark contest.

| Notes | Slowest of scan / search / backlinks | Verdict if slower |
| --- | --- | --- |
| 500 | 0.25s | Still fine for daily use; record the number. |
| 2,000 | 1.00s | Revisit indexing. This is the human-scale miss. |

A vault that has not reached 500 notes has no published miss. Caps remain
10,000 files / 128 MiB; `jotline doctor` warns at 80% of the file cap.

## How to measure

From a development checkout:

```sh
python3 scripts/vault_bench.py --count 500
python3 scripts/vault_bench.py --count 2000
```

`--vault DIR` writes into an existing folder. The default is a temporary
directory that is deleted afterwards. This is not a user-facing `jotline`
command.

CI runs an 80-note vault and asserts the same operations finish within two
seconds so a regression cannot silently turn a scan into a hang.

## Recorded run

Linux cloud agent, Python 3.12, 2026-09-15, idle tmpfs vault:

| Notes | Scan | Search `unique-token-beta` | Backlinks | Verdict |
| --- | --- | --- | --- | --- |
| 80 (CI shape) | covered by tests | covered by tests | covered by tests | Under 2.00s |
| 500 | 0.022s | 0.0004s | 0.0005s | In-memory (≤ 0.25s) |
| 2,000 | 0.080s | 0.0014s | 0.0023s | In-memory (≤ 1.00s) |

Until a 2,000-note run misses 1s, **do not add an index**. Double down on
`doctor`, conflict recovery copies, and ZIP backups instead.

## What *is* in product

- Recovery copies store `recovery_of` in the note header. The draft body is
  unchanged. `jotline recoveries` and Commands → Open a recovery copy list them.
- `jotline backups` lists and verifies local ZIPs. `jotline doctor` warns when
  notes exist without a valid archive, when the newest valid archive is older
  than two days, when displaced `.jotline-displaced-*` files remain, and when
  the scan is at 80% of its file budget.
- Commands → Check vault health shows the same summary inside the app.
