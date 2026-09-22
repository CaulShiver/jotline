"""The outline commands, by name.

Data only, and deliberately free of imports: Settings.validate() checks that a
configured outline shortcut names a real command, and reading a settings file
must not drag in the terminal UI. Doing so cost jotline capture two tenths of
a second on every run, for every user who has ever saved a preference.
"""
from __future__ import annotations

ACTIONS = {
    'new_block': 'Insert sibling block', 'new_child': 'Insert child block',
    'continuation': 'Insert continuation line', 'indent': 'Indent selected branches',
    'outdent': 'Outdent selected branches', 'move_up': 'Move selected branches up',
    'move_down': 'Move selected branches down', 'move_to': 'Move selected branches to…',
    'task': 'Toggle task status', 'fold': 'Fold or expand branch',
    'collapse_all': 'Fold all branches', 'expand_all': 'Expand all branches',
    'zoom': 'Focus branch', 'zoom_out': 'Focus parent', 'home': 'Focus whole note',
    'nav_back': 'Previous outline location', 'nav_forward': 'Next outline location',
    'search': 'Find block, including folded branches', 'restore_folds': 'Restore folds after search',
    'select_block': 'Select or deselect branch', 'select_all': 'Select all visible branches',
    'clear_selection': 'Clear branch selection', 'duplicate': 'Duplicate selected branches',
    'group': 'Group selected sibling branches', 'copy': 'Copy selected branches as Markdown',
    'cut': 'Cut selected branches', 'paste_outline': 'Paste clipboard as outline branches',
    'paste_text': 'Paste clipboard as literal block text', 'delete_branch': 'Delete selected branches',
    'merge': 'Merge block into previous sibling', 'reference': 'Copy permanent block reference',
    'insert_link': 'Insert note link', 'snippet': 'Insert snippet', 'follow_reference': 'Open block reference',
    'embed': 'Preview referenced branch', 'inspector': 'Toggle full-height block inspector',
    'undo': 'Undo edit', 'redo': 'Redo edit', 'save': 'Save note', 'done': 'Switch to Markdown',
}
