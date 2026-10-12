"""Slug rules and the filename policy, before any vault I/O."""
import pytest

from jotline.filenames import (
    SHORT_ID_MIN,
    allocate_filename,
    filename_for,
    header_needs_id,
    readable_parts,
    set_header_id,
    slugify,
)

NOTE = "a1b2c3d4e5f6789012345678abcdef01"


def test_slug_rules():
    assert slugify("Buy milk") == "buy-milk"
    assert slugify("  Buy   milk!! ") == "buy-milk"
    assert slugify("Café au lait") == "cafe-au-lait"
    assert slugify("牛奶") == "note"
    assert slugify("---") == "note"
    assert slugify("Untitled") == "untitled"
    assert slugify("123 go") == "123-go"
    long = slugify("word " * 40)
    assert len(long) <= 60
    assert "--" not in long
    assert long.endswith("word") or not long.endswith("-")


def test_readable_name_splits_on_the_double_hyphen():
    assert readable_parts("buy-milk--a1b2c3.md") == ("buy-milk", "a1b2c3")
    assert readable_parts("buy-milk-a1b2c3.md") is None
    assert readable_parts("a1b2c3d4e5f6789012345678abcdef01.md") is None
    assert readable_parts("daily-2026-10-12.md") is None


def test_short_id_grows_until_the_filename_is_free():
    first = allocate_filename(NOTE, "Buy milk", set())
    assert first == f"buy-milk--{NOTE[:SHORT_ID_MIN]}.md"
    taken = {first}
    # A different note whose 6-character prefix collides.
    other = "a1b2c3ffffffffffffffffffffffffff"
    assert other[:6] == NOTE[:6]
    second = allocate_filename(other, "Buy milk", taken)
    assert second == f"buy-milk--{other[:8]}.md"
    # The note's own current name is not a collision with itself.
    assert allocate_filename(NOTE, "Buy milk", taken, current=first) == first


def test_full_id_is_used_before_giving_up():
    occupied = {f"buy-milk--{NOTE[:length]}.md" for length in range(SHORT_ID_MIN, len(NOTE), 2)}
    occupied.add(f"buy-milk--{NOTE}.md")
    assert allocate_filename(NOTE, "Buy milk", occupied, current="keep.md") == "keep.md"
    assert allocate_filename(NOTE, "Buy milk", occupied) == f"{NOTE}.md"


def test_filename_policy():
    current = f"{NOTE}.md"
    occupied = {current}
    readable = filename_for(NOTE, "Buy milk", encrypted=False, mode="readable",
                            current=current, occupied=occupied)
    assert readable == f"buy-milk--{NOTE[:6]}.md"
    assert filename_for(NOTE, "Buy milk", encrypted=False, mode="keep",
                        current=current, occupied=occupied) == current
    assert filename_for(NOTE, "Buy milk", encrypted=False, mode="opaque",
                        current=readable, occupied={readable}) == current
    assert filename_for(NOTE, "Client Sam", encrypted=True, mode="readable",
                        current=readable, occupied={readable}) == current
    daily = "daily-2026-10-12.md"
    assert filename_for("daily-2026-10-12", "12 October", encrypted=False, mode="readable",
                        current=daily, occupied={daily}) == daily
    assert filename_for("todo", "By hand", encrypted=False, mode="readable",
                        current="todo.md", occupied={"todo.md"}) == "todo.md"


def test_unknown_filename_mode_is_rejected():
    with pytest.raises(AssertionError):
        filename_for(NOTE, "Buy milk", encrypted=False, mode="sideways",  # type: ignore[arg-type]
                     current=f"{NOTE}.md", occupied=set())


def test_header_id_is_added_and_removed_without_touching_the_body():
    raw = "---\njotline: 1\ncollection: \"inbox\"\nupdated: \"2001-01-01T00:00:00+00:00\"\n---\n# Buy milk\n\n"
    with_id = set_header_id(raw, NOTE)
    assert with_id.startswith("---\njotline: 1\nid: \"" + NOTE + "\"\ncollection:")
    assert with_id.endswith("---\n# Buy milk\n\n")
    assert set_header_id(with_id, None) == raw
    assert header_needs_id(f"buy-milk--{NOTE[:6]}.md", NOTE)
    assert not header_needs_id(f"{NOTE}.md", NOTE)


def test_header_id_keeps_crlf_and_a_byte_order_mark():
    raw = "\ufeff---\r\njotline: 1\r\nstarred: true\r\n---\r\n# By hand\r\n"
    updated = set_header_id(raw, NOTE)
    assert updated.startswith("\ufeff---\r\njotline: 1\r\nid: ")
    assert updated.endswith("---\r\n# By hand\r\n")
    assert set_header_id("plain body\n", None) == "plain body\n"
    assert set_header_id("plain body\n", NOTE).endswith("---\nplain body\n")
