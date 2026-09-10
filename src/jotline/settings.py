"""Validated per-vault preferences, stored separately from notes."""
from dataclasses import asdict, dataclass, fields
import json
import os
from pathlib import Path
import tempfile

THEMES = ('jotline', 'nord', 'gruvbox', 'catppuccin-mocha', 'dracula', 'tokyo-night',
          'solarized-dark', 'solarized-light', 'textual-light')


@dataclass
class Settings:
    theme: str = 'jotline'
    line_numbers: bool = False
    soft_wrap: bool = True
    highlight_line: bool = True
    focus_on_start: bool = False
    show_hints: bool = True
    sidebar_width: int = 32
    autosave_seconds: float = 0.7
    sort_order: str = 'updated'
    startup: str = 'new'
    default_collection: str = 'inbox'
    daily_template: str = '# {{date}}\n\n'

    def validate(self):
        for name in ('line_numbers', 'soft_wrap', 'highlight_line', 'focus_on_start', 'show_hints'):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f'{name} must be true or false')
        if self.theme not in THEMES:
            raise ValueError('Unknown theme')
        if type(self.sidebar_width) is not int or not 22 <= self.sidebar_width <= 60:
            raise ValueError('Sidebar width must be 22–60 columns')
        if type(self.autosave_seconds) not in (int, float) or not 0.2 <= self.autosave_seconds <= 5:
            raise ValueError('Autosave interval must be 0.2–5 seconds')
        if self.sort_order not in ('updated', 'created', 'title'):
            raise ValueError('Unknown sort order')
        if self.startup not in ('new', 'daily'):
            raise ValueError('Unknown startup page')
        if self.default_collection not in ('inbox', 'projects', 'areas', 'resources'):
            raise ValueError('Unknown default collection')
        if not isinstance(self.daily_template, str) or len(self.daily_template) > 20000:
            raise ValueError('Daily template must be text under 20,000 characters')

    @classmethod
    def load(cls, path: Path):
        if not path.exists():
            return cls(), ''
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                raise ValueError('Settings must be an object')
            known = {f.name for f in fields(cls)}
            settings = cls(**{k: v for k, v in data.items() if k in known})
            settings.validate()
            return settings, ''
        except (ValueError, TypeError, OSError) as error:
            return cls(), f'Could not load settings; using defaults. {error}'

    def save(self, path: Path):
        self.validate()
        fd, temp = tempfile.mkstemp(prefix='.settings-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(asdict(self), stream, indent=2, ensure_ascii=False)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
