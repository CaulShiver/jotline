"""Modal screens that ignore a second dismissal.

Input.Submitted and OptionList.OptionSelected arrive through the widget queue,
so a key-repeat Enter or a mouse double-click can deliver two dismiss triggers
before the first pop completes. Textual's Screen.dismiss has no guard: a second
pop with one modal on the stack raises ScreenStackError and ends the app, and
with nested modals it silently pops the parent without its result callback.
"""
from __future__ import annotations

from textual.screen import ModalScreen, ScreenResultType


class Modal(ModalScreen[ScreenResultType]):
    _dismissed = False

    def dismiss(self, result: ScreenResultType | None = None):
        if self._dismissed or self.app.screen is not self:
            return None
        self._dismissed = True
        return super().dismiss(result)
