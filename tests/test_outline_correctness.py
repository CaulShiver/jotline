"""Regressions from the outliner research plus independently generated edits."""
import random

import pytest
from markdown_it import MarkdownIt

from jotline.outline_session import OutlineSession, patch
from jotline.outline_state import read_state, write_state
from jotline.outliner import Outline


def shape(outline):
    return [(b.content.strip(), b.parent.content.strip() if b.parent else None) for b in outline.walk()]


def test_child_deletion_preserves_paragraph_after_nested_list():
    outline = Outline('- Parent\n  - Child\n\n  Parent paragraph\n- Other')
    parent = outline.roots[0]
    assert parent.children[0].content == 'Child'
    assert parent.content == 'Parent\n\nParent paragraph'
    assert outline.at_row(3) is parent
    parent.children.clear()
    assert outline.text == '- Parent\n\n  Parent paragraph\n- Other'


def test_parent_edit_preserves_interleaved_content_order():
    outline = Outline('- Parent\n  - Child\n\n  Parent paragraph\n- Other')
    outline.roots[0].set_content('Changed\n\nParent paragraph')
    assert outline.text == '- Changed\n  - Child\n\n  Parent paragraph\n- Other'


@pytest.mark.parametrize('source, count', [
    ('    - literal code\n\n- Real item', 2),
    ('10. Parent\n  - Is this a child?\n11. Next', 3),
    ('- ```\n  text\n  - Child\n- Other', 2),
    ('> - quoted\n>   - quoted child\n\n- Actual', 2),
    ('- Parent\n\t- Child\n', 2),
    ('- Parent\n  ```\n  - code\n  ```\n  - Child', 2),
])
def test_commonmark_boundaries(source, count):
    outline = Outline(source)
    assert outline.text == source
    assert len(list(outline.walk())) == count
    assert shape(Outline(outline.text)) == shape(outline)


def test_number_marker_width_is_respected():
    outline = Outline('10. Parent\n  - Is this a child?\n11. Next')
    assert not outline.roots[0].children


def test_indented_code_has_no_structural_prefix():
    outline = Outline('    - literal code\n\n- Real item')
    assert outline.roots[0].prefix == ''


def test_move_child_does_not_move_parent_tail():
    outline = Outline('- Parent\n  - Child\n\n  Tail\n- Other')
    assert outline.outdent(outline.roots[0].children[0])
    assert outline.text == '- Parent\n\n  Tail\n- Child\n- Other'


def test_parent_and_descendant_selection_operates_once():
    outline = Outline('- A\n  - B\n- C')
    parent = outline.roots[0]
    assert outline.selected_roots({b.uid for b in parent.walk()}) == [parent]
    assert not outline.reparent(parent, parent.children[0])


def test_duplicate_has_new_identity_and_no_reused_anchors():
    outline = Outline('- A ^abc\n  - B ^def\n- C')
    clone = outline.duplicate(outline.roots[0])
    assert clone.content == 'A'
    assert clone.children[0].content == 'B'
    assert len({b.uid for b in outline.walk()}) == 5
    assert outline.roots[0].content.endswith('^abc')


def test_session_undo_restores_identity_but_retains_view_folds():
    original = '- A\n  - B\n- C'
    session = OutlineSession(original)
    parent = session.outline.roots[0]
    uid = parent.uid
    parent.set_content('Changed')
    session.reload(session.outline.text)
    session.outline.roots[0].collapsed = True
    restored = session.reload(original, history=True)
    assert restored.roots[0].uid == uid
    assert restored.roots[0].collapsed


@pytest.mark.parametrize('before,after', [('', 'new'), ('a\r\nb', 'a\r\nnew\r\nb'),
                                         ('abc', 'ab'), ('same', 'same'),
                                         ('é🙂\ntext\n', 'é漢\ntext\n')])
def test_minimal_patch_roundtrips(before, after):
    start, end, replacement = patch(before, after)
    assert before[:start] + replacement + before[end:] == after


def test_revision_guard_and_private_view_state(tmp_path):
    path = tmp_path / '.jotline-outline.json'
    from jotline.outline_session import revision
    state = {'revision': revision('- Secret'), 'folded': [0], 'current': 0}
    write_state(path, 'note', state)
    assert read_state(path, 'note', '- Secret') == state
    assert read_state(path, 'note', '- External edit') == {}
    assert 'Secret' not in path.read_text()
    assert path.stat().st_mode & 0o077 == 0


def test_generated_branch_operations_keep_tree_and_commonmark_in_agreement():
    rng = random.Random(234)
    outline = Outline('\n'.join('- Block ' + str(i) for i in range(25)))
    for _ in range(250):
        blocks = list(outline.walk())
        block = rng.choice(blocks)
        operation = rng.choice(['indent', 'outdent', 'up', 'down', 'task'])
        if operation == 'indent':
            outline.indent(block)
        elif operation == 'outdent':
            outline.outdent(block)
        elif operation in ('up', 'down'):
            outline.move(block, -1 if operation == 'up' else 1)
        else:
            outline.toggle_task(block)
        assert len(list(outline.walk())) == 25
        assert len({b.uid for b in outline.walk()}) == 25
        for parent in outline.walk():
            assert all(child.parent is parent for child in parent.children)
        assert shape(Outline(outline.text)) == shape(outline)
        items = [t for t in MarkdownIt().parse(outline.text) if t.type == 'list_item_open']
        assert len(items) == 25


def test_tabs_inside_content_survive_restructure_and_tab_indented_duplicate():
    outline = Outline('- A\n- Parent\n\t- Child\tx\n\t  more\ty')
    parent = outline.roots[1]
    child = parent.children[0]
    assert child.content == 'Child\tx\nmore\ty'
    assert outline.indent(parent)
    assert '\tx' in outline.text and '\ty' in outline.text
    assert outline.outdent(parent)
    clone = outline.duplicate(child)
    assert clone.content == child.content
    assert clone.parent is parent
    assert len(Outline(outline.text).roots[1].children) == 2


def test_literal_paste_escapes_number_delimiters_and_tilde_fences():
    from jotline.outliner import literal_text
    text = literal_text('1. First\n~~~\n- Item')
    assert text == '1\\. First\n\\~~~\n\\- Item'
    assert len(list(Outline('- Parent\n  ' + text.replace('\n', '\n  ')).walk())) == 1
