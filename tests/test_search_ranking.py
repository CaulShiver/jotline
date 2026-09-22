"""Ranking and the matched line shown under a search result.

Matching alone told a reader which notes came back but never why. These cover
the ordering and the quoted line that answers that.
"""
from jotline.app import Jotline
from jotline.search import excerpt, parse_query, rank, sought
from jotline.store import Vault


class FakeNote:
    def __init__(self, title, body, tags=frozenset()):
        self.id = 'a' * 32
        self.title = title
        self.body = body
        self.tags = set(tags)
        self.created = self.updated = '2026-09-01T00:00:00+00:00'


def score(note, query):
    found = rank(note, parse_query(query))
    return None if found is None else found.score


def line(note, query):
    found = rank(note, parse_query(query))
    return '' if found is None else found.line


def test_a_title_hit_outranks_a_body_hit():
    titled = FakeNote('Kitchen rebuild', 'Nothing else here.')
    mentioned = FakeNote('Shopping', 'Some notes about the kitchen.')
    assert score(titled, 'kitchen') > score(mentioned, 'kitchen')


def test_matching_more_of_the_query_outranks_matching_less():
    both = FakeNote('Notes', 'The kitchen tiling is booked.')
    one = FakeNote('Notes', 'The kitchen is booked.')
    assert score(both, 'kitchen tiling') > score(one, 'kitchen tiling')


def test_a_word_near_the_top_outranks_the_same_word_at_the_bottom():
    early = FakeNote('Notes', 'tiling\n' + 'filler\n' * 50)
    late = FakeNote('Notes', 'filler\n' * 50 + 'tiling\n')
    assert score(early, 'tiling') > score(late, 'tiling')


def test_a_tag_hit_counts_toward_the_score():
    tagged = FakeNote('Notes', 'Body mentions kitchen.', tags={'kitchen'})
    plain = FakeNote('Notes', 'Body mentions kitchen.')
    assert score(tagged, 'kitchen') > score(plain, 'kitchen')


def test_a_query_with_no_words_is_not_ranked():
    # A bare tag or date filter matches every result equally.
    note = FakeNote('Notes', 'Body')
    assert rank(note, parse_query('#kitchen')) is None
    assert rank(note, parse_query('created-after:2026-01-01')) is None
    assert sought(parse_query('#kitchen')) == []


def test_an_excluded_word_is_not_quoted_back():
    assert sought(parse_query('kitchen -tiling')) == ['kitchen']


def test_the_quoted_line_holds_the_match():
    note = FakeNote('Kitchen rebuild', '# Kitchen rebuild\n\nThe tiling is booked for Friday.')
    assert 'tiling' in line(note, 'tiling')


def test_the_note_title_is_not_quoted_back_to_itself():
    # The title is already on the row above.
    note = FakeNote('Kitchen rebuild', '# Kitchen rebuild\n\nThe tiling is booked.')
    assert line(note, 'kitchen') == ''


def test_a_later_line_is_quoted_when_the_title_line_is_skipped():
    note = FakeNote('Kitchen', '# Kitchen\n\nThe kitchen fitter arrives Friday.')
    assert 'fitter' in line(note, 'kitchen')


def test_a_long_line_is_windowed_around_the_match():
    body = 'x' * 400 + ' tiling ' + 'y' * 400
    quoted, offsets = excerpt(body, ['tiling'])
    assert quoted.startswith('…') and quoted.endswith('…')
    assert len(quoted) < 60
    assert quoted[offsets[0][0]:offsets[0][1]] == 'tiling'


def test_offsets_point_at_the_words_in_the_quoted_line():
    quoted, offsets = excerpt('The tiling and the kitchen are booked.', ['tiling', 'kitchen'])
    assert [quoted[start:stop].casefold() for start, stop in offsets] == ['tiling', 'kitchen']


def test_a_match_that_differs_only_in_case_is_still_quoted():
    quoted, offsets = excerpt('The TILING is booked.', ['tiling'])
    assert quoted[offsets[0][0]:offsets[0][1]] == 'TILING'


async def test_search_results_lead_with_the_best_match_and_quote_it(tmp_path):
    vault = Vault(tmp_path)
    vault.save(vault.new('# Shopping\n\nTiling and a kitchen bin, for the bathroom.'))
    vault.save(vault.new('# Kitchen rebuild\n\nThe kitchen tiling is booked for Friday.'))
    app = Jotline(vault)
    async with app.run_test(size=(110, 34)) as pilot:
        app.query_one('#search').value = 'kitchen tiling'
        app.refresh_notes()  # The search box is debounced; do not wait on the timer.
        await pilot.pause()
        rows = [str(app.query_one('#notes').get_option_at_index(i).prompt) for i in range(2)]
        assert rows[0].startswith('Kitchen rebuild')
        assert 'tiling is booked' in rows[0]


async def test_a_note_list_without_a_search_stays_two_lines(tmp_path):
    # The third line is the cost of searching, not of using the list.
    vault = Vault(tmp_path)
    vault.save(vault.new('# Kitchen rebuild\n\nThe tiling is booked.'))
    app = Jotline(vault)
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.pause()
        row = str(app.query_one('#notes').get_option_at_index(0).prompt)
        assert row.count('\n') == 1


async def test_a_tag_search_does_not_add_a_quoted_line(tmp_path):
    vault = Vault(tmp_path)
    vault.save(vault.new('# Kitchen rebuild\n\nBooked for Friday. #home'))
    app = Jotline(vault)
    async with app.run_test(size=(110, 34)) as pilot:
        app.query_one('#search').value = '#home'
        app.refresh_notes()  # The search box is debounced; do not wait on the timer.
        await pilot.pause()
        row = str(app.query_one('#notes').get_option_at_index(0).prompt)
        assert row.count('\n') == 1


def test_a_case_folding_note_does_not_stall_the_search():
    # ß folds to ss, so the folded body is longer than the body. Walking the
    # folded body with body offsets once left the skip position unable to
    # advance, and the search spun until the app was killed.
    body = ('Weißbier, Fußball, Maßnahmen, Großeltern, Fußgänger, '
            'Weißwein, Nußkuchen, Schlußwort, Hauptstraße')
    assert len(body.casefold()) > len(body)
    assert excerpt(body, ['strasse'], body) == ('', ())


def test_the_quoted_line_is_the_line_that_matched():
    # The quote came from wherever the folded offset happened to land, which
    # on a body that grows when folded was a different line entirely.
    body = ('# Reiseplan\n\nAdresse: Hauptstraße 12, Großstraße 7\n'
            'tiling\nKontonummer DE89 3704 0044 0532 0130 00\n')
    line, _ = excerpt(body, ['tiling'], 'Reiseplan')
    assert line == 'tiling'


def test_marks_fall_on_the_words_they_name():
    line, offsets = excerpt('Weißes tiling hier', ['tiling'], 'Titel')
    assert [line[start:stop] for start, stop in offsets] == ['tiling']


def test_a_folded_match_marks_the_characters_it_came_from():
    line, offsets = excerpt('Hauptstrasse und Hauptstraße', ['strasse'], 'Titel')
    assert [line[start:stop] for start, stop in offsets] == ['strasse', 'straße']


def test_skipping_repeated_title_headings_stays_linear():
    # Every heading line used to restart a full-body scan for each word, which
    # took ten seconds over this note; walking the lines once takes a fifth of
    # a second. The bound is loose enough for a loaded runner and still far
    # under what the quadratic scan cost.
    import time

    body = '# Weekly\n' * 64_000
    start = time.perf_counter()
    excerpt(body, ['weekly', 'b3f1c2d4'], 'Weekly')
    assert time.perf_counter() - start < 3
