"""Small, literal query language shared by the UI, saved views and CLI."""
from datetime import date
import shlex


def compile_query(query):
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
        elif not separator or field not in {'tag', 'title', 'created-after', 'created-before', 'updated-after', 'updated-before'}:
            field, value = 'text', term
        if field.endswith(('-after', '-before')):
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
                found = value in note.body.casefold() or value in note.id
            else:
                attribute, direction = field.split('-')
                stamp = getattr(note, attribute)[:10]
                found = bool(stamp) and (stamp >= value if direction == 'after' else stamp <= value)
            if found == excluded:
                return False
        return True
    return matches
