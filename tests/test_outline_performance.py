"""Work-count regressions for the hot path; no hardware timing thresholds."""
from unittest.mock import patch as mock_patch
from unittest.mock import PropertyMock

from textual.widgets import TextArea

from jotline.app import Jotline
from jotline.outline_session import OutlineSession, revision
from jotline.outliner import Outline
from jotline.store import Vault


def test_content_snapshots_reuse_rows_without_walking_unchanged_tree():
    session = OutlineSession('- Parent\n  - Child\n- Other')
    rows = session.outline.rows()
    session.remember(session.outline.text, rows, content_only=True)
    first = session.identities[revision(session.outline.text)]
    session.outline.roots[1].set_content('Edited')
    text = session.outline.text
    with mock_patch.object(session.outline, 'walk', side_effect=AssertionError('whole-tree walk')):
        session.remember(text, rows, content_only=True)
    assert session.identities[revision(text)] is first
    # Structural history still captures current folds, identities and row changes.
    session.outline.roots[0].collapsed = True
    session.remember()
    session.outline.roots[1].set_content('Two\nlines')
    session.reload(text, history=True)
    assert session.outline.roots[0].collapsed
    assert session.outline.roots[1].uid == first[-1][1]


async def test_short_outline_rows_only_build_rich_text_for_viewport(tmp_path, monkeypatch):
    from jotline import outline_view
    rich_text = outline_view.Text
    constructed = []

    def counted_text(*args, **kwargs):
        constructed.append(args)
        return rich_text(*args, **kwargs)

    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 32)) as pilot:
        body = '\n'.join(f'- Item {index}' for index in range(500))
        app.editor().load_text(body)
        await pilot.pause()
        monkeypatch.setattr(outline_view, 'Text', counted_text)
        app.action_outliner()
        await pilot.pause()
        screen = app.screen
        assert len(constructed) < 250
        assert screen.view().virtual_size.height == 500
        with mock_patch.object(Outline, 'text', new_callable=PropertyMock,
                               side_effect=AssertionError('idle source serialization')):
            screen.update_save_status()
        screen.choose(screen.outline.roots[-1])
        screen.action_edit_block()
        with screen.block_editor().prevent(TextArea.Changed):
            screen.block_editor().insert_checked(' 漢🙂' * 70)
        assert screen.flush()
        await pilot.pause()
        assert screen.view().locations[screen.current.uid][1] > 1
        assert screen.source.text == screen.outline.text
        screen.action_undo()
        assert screen.source.text == body
        app.editor().load_text('- External replacement')
        screen.update_save_status()
        assert screen.outline.text == '- External replacement'
