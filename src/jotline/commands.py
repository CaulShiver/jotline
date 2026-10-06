"""One user-visible palette action."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable


# The palette opens on this set. Everything else stays one filter away.
EVERYDAY_COMMANDS = frozenset({
    "new",
    "daily",
    "search",
    "open",
    "recent",
    "find",
    "task",
    "link",
    "follow",
    "star",
    "move:inbox",
    "move:archive",
    "move:trash",
    "history",
    "save",
    "settings",
    "quit",
})


def writing_group(command: Command) -> Command:
    """Keep the everyday palette on the writing loop, whatever a call site asked for."""
    group = "everyday" if command.key in EVERYDAY_COMMANDS else "more"
    if command.group == group:
        return command
    return replace(command, group=group)


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
