"""One user-visible palette action."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Command:
    """Keeping its label and handler together prevents the palette from drifting
    away from the action dispatcher as features are added.
    """

    key: str
    label: str
    handler: Callable[[], None]
    hotkey_action: str | None = None
    group: str = "more"
