"""Small, literal query language shared by the UI, saved views and CLI."""
from collections.abc import Callable
from datetime import date
import shlex

DATE_FIELDS = ('created-after', 'created-before', 'updated-after', 'updated-before')
FIELDS = ('tag', 'title', *DATE_FIELDS)


def compile_query(query: str) -> Callable[[object], bool]:
    """A note predicate for a query of words, #tags, field:value terms and -exclusions."""
    try:
        terms = shlex.split(query.casefold())
    except ValueError:
        # An unfinished quote is normal while typing in the live search field.
        terms = query.casefold().replace('"', '').split()
    predicates = []
    for term in terms:
        excluded = term.startswith('-') and len(term) > 1
        term = term[1:] if excluded else term
        field, separator, value = term.partition(':')
        if term.startswith('#'):
            field, value = 'tag', term[1:]
        elif not separator or field not in FIELDS:
            field, value = 'text', term
        if field in DATE_FIELDS:
            if value != 'today':
                try:
                    parsed = date.fromisoformat(value)
                    if parsed.isoformat() != value:
                        raise ValueError('Non-canonical date')
                except ValueError:
                    raise ValueError('Date filters use YYYY-MM-DD or today') from None
            else:
                value = date.today().isoformat()
        predicates.append((field, value, excluded))

    def matches(note):
        for field, value, excluded in predicates:
            if field == 'tag':
                found = value in note.tags
            elif field == 'title':
                found = value in note.title.casefold()
            elif field == 'text':
                # Match IDs only by a meaningful prefix; short terms would
                # otherwise hit random hex digits in almost every note.
                found = value in note.body.casefold() or (len(value) >= 8 and note.id.startswith(value))
            else:
                attribute, direction = field.split('-')
                stamp = getattr(note, attribute)[:10]
                found = bool(stamp) and (stamp >= value if direction == 'after' else stamp <= value)
            if found == excluded:
                return False
        return True
    return matches
