"""Snapshot-based link lookup keeps navigation fast without stale aliases."""
from dataclasses import replace
from types import SimpleNamespace

from jotline.connect_ui import Connections
from jotline.links import incoming_refs, index_link_targets, outgoing_refs, resolve_link_targets
from jotline.store import Note, Vault


def test_index_preserves_alias_ambiguity_order_and_anchor_resolution():
    long_heading = 'Heading ' + 'x' * 120
    notes = [Note('first', '# Same'), Note('second', '# Same'), Note('long', '# ' + long_heading),
             Note('Same', '# Different')]
    index = index_link_targets(notes)
    for target in ('Same', 'first', 'second', long_heading, long_heading[:100], 'missing'):
        assert index.get(target, []) == resolve_link_targets(notes, target)
    refs = outgoing_refs('[[Same]] [[Same]] [[first#^block]] [[missing]]', notes, target_index=index)
    assert [(ref.target, ref.note_id, ref.status) for ref in refs] == [
        ('Same', 'first', 'ambiguous'), ('Same', 'second', 'ambiguous'), ('Same', 'Same', 'ambiguous'),
        ('first#^block', 'first', 'ok'), ('missing', None, 'broken'),
    ]


def test_many_outgoing_links_read_aliases_once_per_snapshot():
    class CountedNote:
        locked = False

        def __init__(self, index):
            self.id = f'id-{index}'
            self.body = ''
            self.reads = 0

        @property
        def title(self):
            self.reads += 1
            return self.id

        @property
        def heading(self):
            self.reads += 1
            return self.id

    notes = [CountedNote(index) for index in range(200)]
    body = '\n'.join(f'[[id-{index}]]' for index in range(80))
    assert len(outgoing_refs(body, notes)) == 80
    # Two alias reads per note, plus one title for each resulting connection.
    assert sum(note.reads for note in notes) == 2 * len(notes) + 80
    for note in notes:
        note.reads = 0
    assert outgoing_refs('No links, including `[[code]]`.', notes) == []
    assert sum(note.reads for note in notes) == 0


def test_workspace_index_refreshes_after_rename_workspace_change_and_lock(tmp_path):
    class Connected(Connections):
        def __init__(self):
            self.vault = Vault(tmp_path)
            self.workspace = 'default'
            self._link_notes = None
            self._link_workspace = ''

    app = Connected()
    first = Note('first', '# Original')
    other = Note('other', '# Other', workspace='work')
    app.cached_workspace_notes([first, other])
    original = app.cached_link_targets()
    assert app.cached_link_targets() is original
    assert 'Original' in original and 'Other' not in original
    renamed = replace(first, body='# Renamed')
    app.cached_workspace_notes([renamed, other])
    assert 'Original' not in app.cached_link_targets()
    assert app.cached_link_targets()['Renamed'] == [renamed]
    app.workspace = 'work'
    app.vault.notes = lambda: [renamed, other]
    assert app.cached_link_targets()['Other'] == [other]
    assert 'Renamed' not in app.cached_link_targets()
    app.workspace = 'default'
    sealed = replace(renamed, body='', sealed='ciphertext', encrypted=True)
    app.cached_workspace_notes([sealed, other])
    assert 'Renamed' not in app.cached_link_targets()
    assert app.cached_link_targets()['first'] == [sealed]


def test_current_outgoing_uses_live_buffer_with_cached_aliases(tmp_path):
    class Connected(Connections):
        def __init__(self):
            self.vault = Vault(tmp_path)
            self.workspace = 'default'
            self._link_notes = None
            self._link_workspace = ''
            self.current = Note('source', '# Source\n[[Old]]')
            self.buffer = SimpleNamespace(text='# Source\n[[New]]')

        def editor(self):
            return self.buffer

    app = Connected()
    target = Note('target', '# New')
    app.cached_workspace_notes([app.current, target])
    assert [ref.target for ref in app.current_outgoing()] == ['New']
    index = app.cached_link_targets()
    app.buffer.text = '[[Missing]]'
    assert app.current_outgoing()[0].status == 'broken'
    assert app.cached_link_targets() is index


def test_backlink_prefilter_preserves_anchors_fences_and_first_occurrence():
    target = Note('target', '# Title')
    source = Note('source', '# Source\n`[[target]]`\n[[Title#^anchor]]\n[[target]]')
    unrelated = Note('unrelated', '# Unrelated\n[[elsewhere]]')
    fenced = Note('fenced', '# Example\n```\n[[target]]\n```')
    refs = incoming_refs(target, [source, unrelated, fenced, target])
    assert [(ref.note_id, ref.target) for ref in refs] == [('source', 'Title#^anchor')]
