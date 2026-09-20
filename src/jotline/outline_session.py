"""Derived block identity and bounded source patches over the canonical editor."""
from __future__ import annotations

from hashlib import sha256

from .outliner import Outline


def revision(text: str) -> str:
    return sha256(text.encode('utf-8')).hexdigest()


def patch(before: str, after: str) -> tuple[int, int, str]:
    """Find changed lines in C, then narrow the two boundary lines.

    Splitting and comparing whole lines avoids a Python loop over every
    character on every keystroke in a large note.
    """
    a, b = before.splitlines(keepends=True), after.splitlines(keepends=True)
    first = 0
    while first < min(len(a), len(b)) and a[first] == b[first]:
        first += 1
    last = 0
    while last < min(len(a), len(b)) - first and a[-last - 1] == b[-last - 1]:
        last += 1
    start = sum(map(len, a[:first]))
    end = len(before) - sum(map(len, a[len(a) - last:])) if last else len(before)
    replacement = ''.join(b[first:len(b) - last if last else len(b)])
    old = before[start:end]
    left = 0
    while left < min(len(old), len(replacement)) and old[left] == replacement[left]:
        left += 1
    right = 0
    while right < min(len(old), len(replacement)) - left and old[-right - 1] == replacement[-right - 1]:
        right += 1
    return start + left, end - right, replacement[left:len(replacement) - right if right else len(replacement)]


class OutlineSession:
    def __init__(self, text: str):
        self.outline = Outline(text)
        self.identities: dict[str, list[tuple[int, str]]] = {}
        self.folds: dict[str, bool] = {}
        self.remember()

    def remember(self, text=None, rows=None, *, content_only=False) -> None:
        """Save undo identities, reusing an unchanged row map while typing.

        The inline editor replaces its row map whenever source rows change.
        Content-only snapshots cannot remove blocks; their folds are captured
        before structural edits and by reload(), rather than on every key.
        """
        rows = self.outline.rows() if rows is None else rows
        if content_only and rows is getattr(self, '_last_rows', None):
            entries = self._last_entries
        else:
            entries = [(row, block.uid) for block, row in rows.items()]
            previous = getattr(self, '_last_entries', None)
            if entries == previous:
                entries = previous
        self._last_rows = rows
        self._last_entries = entries
        self.identities[revision(self.outline.text if text is None else text)] = entries
        # Bound derived history independently of Textual's text undo history.
        while len(self.identities) > 128:
            del self.identities[next(iter(self.identities))]
        if not content_only:
            self.folds.update((b.uid, b.collapsed) for b in self.outline.walk())
        if len(self.folds) > 2 * len(rows) + 100:
            live_ids = {uid for entries in self.identities.values() for _, uid in entries}
            self.folds = {uid: folded for uid, folded in self.folds.items() if uid in live_ids}

    def reload(self, text: str, *, history: bool = False) -> Outline:
        previous = self.outline
        self.folds.update((b.uid, b.collapsed) for b in previous.walk())
        self.outline = Outline(text)
        known = dict(self.identities.get(revision(text), [])) if history else {}
        if known:
            for block, row in self.outline.rows().items():
                block.uid = known.get(row, block.uid)
        else:
            self.outline.reconcile(previous)
        for block in self.outline.walk():
            block.collapsed = self.folds.get(block.uid, block.collapsed)
        self.remember()
        return self.outline
