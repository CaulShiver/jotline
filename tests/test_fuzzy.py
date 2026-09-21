import time

import pytest

from jotline.fuzzy import CANDIDATE_LIMIT, match, match_term, word_starts


def scored(query, label):
    return match(query.casefold().split(), label)[0]


def marked(query, label):
    offsets = set(match(query.casefold().split(), label)[1])
    return ''.join(c.upper() if i in offsets else c for i, c in enumerate(label.casefold()))


def test_letters_in_order_match_without_being_adjacent():
    assert scored('mtgnts', 'Meeting notes')
    assert not scored('mtgnts', 'Export to PDF')


def test_every_substring_query_still_matches():
    # The filter this replaced required each term to be a literal substring.
    # Anything it found must still be found, or a user loses a result.
    labels = ['Meeting notes', 'Daily log', 'Project review', 'Export to PDF']
    for query in ['note', 'daily log', 'proj', 'export pdf', 'to']:
        terms = query.casefold().split()
        for label in labels:
            if all(term in label.casefold() for term in terms):
                assert match(terms, label)[0], (query, label)


def test_every_term_must_match():
    assert scored('project review', 'Project review')
    assert not scored('project missing', 'Project review')


def test_a_whole_word_beats_scattered_letters():
    assert scored('note', 'Meeting notes') > scored('note', 'Nothing on the table')


def test_an_exact_title_beats_a_longer_one():
    assert scored('note', 'note') > scored('note', 'Meeting notes')


def test_an_earlier_match_beats_a_later_one():
    assert scored('log', 'Log of the week') > scored('log', 'A week and then the log')


def test_the_run_is_marked_where_a_reader_expects_it():
    # Matching greedily alone would mark the leading "no" of "no meeting".
    assert marked('note', 'no meeting notes') == 'no meeting NOTEs'


def test_case_and_folding_do_not_change_the_match():
    assert scored('MEETING', 'meeting notes')
    assert scored('meeting', 'MEETING NOTES')


def test_offsets_stay_inside_the_label():
    label = 'Meeting notes'
    for offset in match(['note'], label)[1]:
        assert 0 <= offset < len(label)


def test_a_long_label_is_matched_up_to_the_limit():
    label = 'x' * (CANDIDATE_LIMIT + 50) + 'tail'
    assert not scored('tail', label)
    assert scored('x', label)


def test_an_empty_query_matches_nothing_on_its_own():
    assert match([], 'Meeting notes')[0] == 0.0
    assert match_term('', 'meeting notes')[0] == 0.0


def test_word_starts_finds_the_first_letter_of_each_word():
    assert word_starts('meeting notes') == frozenset({0, 8})
    assert word_starts('  spaced') == frozenset({2})
    assert word_starts('') == frozenset()


@pytest.mark.parametrize('query', ['uoiea', 'aeiouaeiou', 'aaaaaa'])
def test_repeated_letters_do_not_stall_the_picker(query):
    """Exhaustive offset search is exponential here; this must stay linear.

    Labels are note titles, so a vault can contain one of these by accident,
    and a picker runs the matcher over every note on every keystroke.
    """
    label = ('aeiou ' * 40).strip()
    start = time.perf_counter()
    match([query], label)
    assert time.perf_counter() - start < 0.05
