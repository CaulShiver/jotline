"""Visible note connections: panel, follow, and create-from-broken-[[link]]."""
from __future__ import annotations

from textual import events
from textual.widgets import Static

from .links import (
    LinkRef,
    connection_mark,
    incoming_refs,
    outgoing_refs,
    stabilize_wiki_target,
    wiki_link_at,
)
from .modal import Palette
from .store import wiki_link


class ConnectionsBar(Static):
    """Clickable summary of incoming and outgoing note links."""

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.app.action_backlinks()


class Connections:
    """Bound onto Jotline; not inherited."""

    def connect_commands(self, Command):
        return [
            Command("link", "Insert note link", lambda: self.select_related_note("link")),
            Command("follow", "Follow a link in this note", self.action_follow),
            Command("backlinks", "Show connections", self.action_backlinks, "backlinks"),
        ]

    def cached_workspace_notes(self, notes=None, *, refresh: bool = False):
        if notes is not None or refresh or self._link_notes is None or self._link_workspace != self.workspace:
            snapshot = self.vault.notes() if notes is None else notes
            self._link_notes = self.vault.workspace_notes(self.workspace, notes=snapshot)
            self._link_workspace = self.workspace
            self._incoming_for = ""
        return self._link_notes

    def current_outgoing(self):
        if self.current.locked:
            return []
        try:
            body = self.editor().text
        except Exception:
            body = self.current.body
        return outgoing_refs(body, self.cached_workspace_notes())

    def current_incoming(self, *, refresh: bool = False):
        notes = self.cached_workspace_notes(refresh=refresh)
        if refresh or self._incoming_for != self.current.id:
            self._incoming = incoming_refs(self.current, notes)
            self._incoming_for = self.current.id
        return self._incoming

    def connection_counts(self) -> str:
        if self.current.locked:
            return "locked · unlock to see its links"
        incoming = self.current_incoming()
        outgoing = self.current_outgoing()
        broken = sum(item.status == "broken" for item in outgoing)
        text = f"←{len(incoming)} →{len(outgoing)}"
        if broken:
            text += f" · {broken} broken"
        return text

    def connections(self, notes=None, *, refresh: bool = False) -> None:
        if notes is not None:
            self.cached_workspace_notes(notes, refresh=True)
        incoming = self.current_incoming(refresh=refresh)
        outgoing = self.current_outgoing()
        if self.current.locked:
            line = "Encrypted note (locked). Unlock to see its outgoing links."
        elif not incoming and not outgoing:
            backlinks_key = self.settings.effective_hotkeys.get("backlinks") or "alt+k"
            line = self.shortcut_text(
                f"No links yet. Type [[ to connect this note, or {backlinks_key} / ctrl+p → Insert note link")
        else:
            broken = [item for item in outgoing if item.status == "broken"]
            titles = [item.title for item in incoming[:3] if item.title]
            line = f"← {len(incoming)}  → {len(outgoing)}"
            if titles:
                line += "  " + " · ".join(titles)
            if broken:
                line += f"  ·  {len(broken)} broken"
            backlinks_key = self.settings.effective_hotkeys.get("backlinks") or "alt+k"
            line += self.shortcut_text(f"  ·  {backlinks_key} connections")
        self.query_one("#connections", Static).update(line)
        if self.compact_layout:
            self.status("Saving…" if self.dirty else ("Saved" if self.current.original else "Ready"))

    def select_related_note(self, mode: str) -> None:
        self.capture_current_buffer()
        if mode == "backlinks":
            self.action_backlinks()
            return
        if mode == "follow":
            self.action_follow()
            return
        notes = [note for note in self.vault.search(workspace=self.workspace) if note.id != self.current.id]
        if not notes:
            self.notify("No notes to link yet. Capture another thought first.")
            return

        def picked(note_id: str | None) -> None:
            if not note_id:
                return
            note = next(note for note in notes if note.id == note_id)
            self.editor().insert(wiki_link(note))
            self.editor().focus()

        self.push_screen(Palette(self.note_choices(notes), "Choose a note"), picked)

    def action_backlinks(self) -> None:
        self.capture_current_buffer()
        incoming = self.current_incoming()
        outgoing = self.current_outgoing()
        if self.current.locked:
            self.notify("Encrypted note (locked). Unlock to see its outgoing links.")
        choices = self.connection_choices(incoming, outgoing)
        if not choices:
            self.notify("No links yet. Type [[ to connect this note, or insert a note link.")
            return

        def picked(key: str | None) -> None:
            if not key:
                return
            if key.startswith("create:"):
                self.create_from_link(key.removeprefix("create:"))
            elif key.startswith("open:"):
                self.load_id(key.removeprefix("open:"))

        self.push_screen(Palette(choices, "Connections"), picked)

    def action_follow(self) -> None:
        self.capture_current_buffer()
        editor = self.editor()
        row, column = editor.cursor_location
        if link := wiki_link_at(editor.text, row, column):
            self.follow_wiki_target(link.target)
            return
        outgoing = self.current_outgoing()
        resolved = [item for item in outgoing if item.status != "broken"]
        broken = [item for item in outgoing if item.status == "broken"]
        if len(resolved) == 1 and resolved[0].note_id:
            self.load_id(resolved[0].note_id)
            return
        if resolved:
            notes = [note for note in self.cached_workspace_notes()
                     if note.id in {item.note_id for item in resolved}]
            self.push_screen(Palette(self.note_choices(notes), "Follow a link"),
                             lambda key: self.load_id(key) if key else None)
            return
        if broken:
            self.follow_wiki_target(broken[0].target)
            return
        self.notify("No link under the cursor. Place the cursor on [[…]] or insert a note link.")

    def follow_wiki_target(self, target: str) -> None:
        matches = [note for note in self.cached_workspace_notes()
                   if target in {note.id, note.title, note.heading}]
        if len(matches) == 1:
            self.load_id(matches[0].id)
            return
        if len(matches) > 1:
            self.push_screen(Palette(self.note_choices(matches), f"“{target}” matches {len(matches)} notes"),
                             lambda key: self.load_id(key) if key else None)
            return
        self.notify(f"No note named {target}. Create it, or pick another link.")
        self.push_screen(Palette([("create:" + target, f"Create note “{target}”")], "Broken link"),
                         lambda key: self.create_from_link(target) if key else None)

    def create_from_link(self, target: str) -> None:
        title = " ".join(target.strip().split())
        if not title:
            self.notify("That link has no title to create.")
            return
        if not self.save_current():
            return
        note = self.new_note(f"# {title}\n")
        try:
            self.vault.save(note)
        except (OSError, ValueError) as error:
            self.notify(str(error), severity="error")
            return
        rewritten = stabilize_wiki_target(self.editor().text, target, note)
        if rewritten != self.editor().text:
            self.editor().load_text(rewritten)
            self.current.body = self.editor().text
            self._editor_baseline = self.editor().text
            self.dirty = True
            if not self.save_current():
                self.notify("Created the note, but could not update the [[link]] to its stable ID.",
                            severity="warning")
        self.connections(refresh=True)
        self.load(note)
        self.refresh_notes()
        self.notify(f"Created “{note.title}” from the broken link.")

    def connection_choices(self, incoming: list[LinkRef], outgoing: list[LinkRef]) -> list[tuple[str, str]]:
        choices = []
        seen: set[str] = set()
        for item in incoming:
            key = "open:" + (item.note_id or item.target)
            if key in seen:
                continue
            seen.add(key)
            snippet = f" · {item.snippet}" if item.snippet else ""
            choices.append((key, f"← {item.title or item.target}{snippet}"))
        for item in outgoing:
            if item.status == "broken":
                key = "create:" + item.target
                if key in seen:
                    continue
                seen.add(key)
                snippet = f" · {item.snippet}" if item.snippet else ""
                choices.append((key, f"! {item.target} — no matching note{snippet}"))
                continue
            if item.status not in {"ok", "ambiguous"}:
                raise ValueError(f"unknown link status: {item.status}")
            key = "open:" + (item.note_id or item.target)
            if key in seen:
                continue
            seen.add(key)
            snippet = f" · {item.snippet}" if item.snippet else ""
            choices.append((key, f"{connection_mark(item.status)} {item.title or item.target}{snippet}"))
        return choices
