"""Names for interactive controls. Headless tests cannot certify a screen reader."""
from __future__ import annotations

from typing import TypeVar

from textual.widget import Widget
from textual.widgets import Button, Footer, Input, OptionList, Select, SelectionList, Switch, TextArea

INTERACTIVE = (Button, Input, TextArea, OptionList, Select, SelectionList, Switch)
COPY_REQUEST = "Copy requested. Your terminal must allow OSC 52 clipboard access."

A11Y_NOTES = """Clipboard, input methods, and screen readers

Copy sends an OSC 52 request. Jotline cannot confirm that the system clipboard
changed. Terminal.app often blocks OSC 52. Many Linux terminals can allow it.
If copy appears to do nothing, check the terminal's clipboard permissions, not
a Jotline setting.

Input methods compose characters in the terminal. Jotline stores the Unicode it
receives. Combining marks, CJK, Arabic, and emoji round-trip as entered. If
composition looks wrong, check the terminal IME (IBus, Fcitx, macOS).

Screen-reader announcements depend on the emulator. VoiceOver with Terminal.app
and Orca with GNOME each need a filled report in docs/terminal-reports/ before
calling 1.0. Automated tests only prove that controls have names. Windows is
out of scope.

Esc returns to writing. Ctrl+, opens Settings. Ctrl+P lists every command.
"""

WidgetT = TypeVar("WidgetT", bound=Widget)


def named(widget: WidgetT, tooltip: str) -> WidgetT:
    """Attach a tooltip after construction for widgets that reject a tooltip= kwarg."""
    widget.tooltip = tooltip
    return widget


def id_name(widget: Widget) -> str:
    return (widget.id or "").replace("-", " ").strip()


def control_name(widget: Widget) -> str:
    """Visible or tooltip name a screen reader could use. Empty means unlabeled."""
    tooltip = getattr(widget, "tooltip", None)
    if tooltip:
        return str(tooltip).strip()
    if isinstance(widget, Button):
        return str(widget.label).strip()
    if isinstance(widget, Input):
        return (widget.placeholder or widget.value or "").strip() or id_name(widget)
    if isinstance(widget, TextArea):
        return id_name(widget)
    if isinstance(widget, (OptionList, Select, SelectionList, Switch)):
        return id_name(widget)
    return id_name(widget)


def unlabeled_controls(root: Widget) -> list[Widget]:
    """Interactive widgets with no tooltip, label, placeholder, or id-derived name."""
    found = []
    for widget in root.query(Widget):
        if isinstance(widget, Footer):
            continue
        if not isinstance(widget, INTERACTIVE):
            continue
        if widget.id in {"commands", "notes"}:
            # Named by a heading or count Static next to the list.
            continue
        if type(widget).__name__ == "SelectOverlay":
            # Internal OptionList for an already-named Select.
            continue
        if not control_name(widget):
            found.append(widget)
    return found
