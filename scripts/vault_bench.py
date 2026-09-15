#!/usr/bin/env python3
"""Build a synthetic vault and time search plus backlinks.

Search stays an in-memory scan unless a measured run misses the bar in
docs/vault-scale.md. This script is a measurement tool, not a user command.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jotline.bench import SEARCH_BARS_SECONDS, measure_vault, populate_synthetic_vault, verdict
from jotline.store import Vault


def main() -> None:
    parser = argparse.ArgumentParser(description="Time Jotline search and backlinks on a synthetic vault")
    parser.add_argument("--count", type=int, default=500, help="Number of notes to write")
    parser.add_argument("--vault", type=Path, help="Existing empty directory; default is a temp folder")
    parser.add_argument("--body-words", type=int, default=40)
    args = parser.parse_args()
    folder = args.vault
    if folder is None:
        temporary = tempfile.TemporaryDirectory(prefix="jotline-bench-")
        folder = Path(temporary.name)
    else:
        temporary = None
        folder.mkdir(parents=True, exist_ok=True)
    try:
        vault = Vault(folder)
        hub = populate_synthetic_vault(vault, args.count, body_words=args.body_words)
        timings = measure_vault(vault, hub)
        print(f"notes={args.count}")
        print(f"vault={folder}")
        for item in timings:
            print(f"{item.label}\t{item.seconds:.4f}s\thits={item.hits}")
        print(verdict(args.count, timings))
        bars = ", ".join(f"{size}<={budget:.2f}s" for size, budget in sorted(SEARCH_BARS_SECONDS.items()))
        print(f"published bars: {bars}")
    finally:
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    main()
