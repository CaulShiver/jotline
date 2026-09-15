"""Synthetic vaults for search and backlink timing. Not a public CLI surface."""
from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from .store import Vault, wiki_link

# Human-scale bars from the durability plan. Exceeding them is the signal to
# consider an index; until then search stays an in-memory scan.
SEARCH_BARS_SECONDS = {500: 0.25, 2000: 1.0}
CI_NOTE_COUNT = 80
CI_BUDGET_SECONDS = 2.0
DEFAULT_BODY_WORDS = 40


@dataclass(frozen=True)
class Timing:
    label: str
    seconds: float
    hits: int


def _body(index: int, words: int, hub: str) -> str:
    filler = " ".join(f"word{index % 97}-{n}" for n in range(words))
    title = f"# Synthetic note {index:04d}"
    if index == 0:
        return f"{title}\n\nHub for backlinks. unique-token-alpha {filler}\n"
    if index % 3 == 0:
        return f"{title}\n\nSee {hub}. unique-token-beta {filler}\n"
    return f"{title}\n\nunique-token-gamma {filler}\n"


def populate_synthetic_vault(vault: Vault, count: int, *, body_words: int = DEFAULT_BODY_WORDS) -> str:
    """Write ``count`` notes. Returns the hub note ID every third note links to."""
    if count < 2:
        raise ValueError("A synthetic vault needs at least two notes")
    hub_note = vault.new("# Synthetic note 0000\n\nplaceholder\n")
    hub_note.body = _body(0, body_words, "")
    vault.save(hub_note)
    link = wiki_link(hub_note)
    for index in range(1, count):
        note = vault.new(_body(index, body_words, link))
        vault.save(note)
    return hub_note.id


def measure_vault(vault: Vault, hub_id: str) -> list[Timing]:
    """Time a cold scan, a typical search, and backlinks for the hub note."""
    vault.invalidate_cache()
    started = perf_counter()
    notes = vault.notes()
    scan = Timing("scan", perf_counter() - started, len(notes))
    started = perf_counter()
    found = vault.search("unique-token-beta", notes=notes)
    search = Timing("search unique-token-beta", perf_counter() - started, len(found))
    hub = vault.read(hub_id)
    started = perf_counter()
    linked = vault.backlinks(hub, notes=notes)
    backlinks = Timing("backlinks hub", perf_counter() - started, len(linked))
    return [scan, search, backlinks]


def bar_for(count: int) -> float | None:
    """Bar for the largest documented size this vault has reached, if any."""
    applicable = [(size, budget) for size, budget in SEARCH_BARS_SECONDS.items() if count >= size]
    if not applicable:
        return None
    return max(applicable)[1]


def verdict(count: int, timings: list[Timing]) -> str:
    """Whether search/backlinks still clear the human-scale bar."""
    budget = bar_for(count)
    slowest = max(item.seconds for item in timings)
    if budget is None:
        return (f"No published bar below {min(SEARCH_BARS_SECONDS)} notes; "
                f"slowest step {slowest:.3f}s")
    if slowest <= budget:
        return (f"In-memory scan is enough at {count} notes "
                f"(slowest {slowest:.3f}s ≤ {budget:.2f}s bar). Do not add an index.")
    return (f"Search or backlinks missed the {budget:.2f}s bar at {count} notes "
            f"(slowest {slowest:.3f}s). Revisit indexing.")
