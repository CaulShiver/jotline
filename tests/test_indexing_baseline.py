"""Baseline timings so an index is added only after a measured need.

Search and backlinks both walk `Vault.notes()` / `workspace_notes()`. This
keeps a cheap synthetic vault under a generous budget so a later index has a
number to beat. It is not a performance guarantee.
"""
from time import perf_counter

from jotline.store import Vault


def test_search_and_backlinks_share_a_full_scan_and_stay_interactive(tmp_path):
    vault = Vault(tmp_path)
    hub = vault.new("# Hub\n\nCenter of the graph")
    vault.save(hub)
    for index in range(200):
        note = vault.new(f"# Note {index}\n\nBody {index} links to [[{hub.id}|Hub]]")
        vault.save(note)

    start = perf_counter()
    found = vault.search("Body 42", workspace="default")
    search_ms = (perf_counter() - start) * 1000
    start = perf_counter()
    backlinks = vault.backlinks(hub)
    backlink_ms = (perf_counter() - start) * 1000
    start = perf_counter()
    connections = vault.connections(hub)
    connections_ms = (perf_counter() - start) * 1000

    assert [note.id for note in found]
    assert len(backlinks) == 200
    assert len(connections.incoming) == 200
    # A later inverted index should beat these on a vault this size or larger.
    # 200 notes is still a full scan; keep the budget loose for CI machines.
    assert search_ms < 1500
    assert backlink_ms < 1500
    assert connections_ms < 2000
