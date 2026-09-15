"""Opt-in note encryption, composed into the main app."""
from __future__ import annotations

from .crypto import EncryptionError, check_passphrase
from .modal import TextPrompt

LOST_PASSPHRASE = "There is no way to open encrypted notes without the passphrase."


class Encryption:
    """Passphrase and note sealing. Bound onto Jotline; not inherited."""

    def encryption_commands(self, Command):
        return [Command(key, label, handler) for key, label, handler in [
            ("encrypt", "Encrypt this note", self.encrypt_current),
            ("decrypt", "Remove encryption from this note", self.decrypt_current),
            ("unlock", "Unlock encrypted notes", self.prompt_unlock),
            ("lock", "Lock encrypted notes", self.lock_notes),
            ("passphrase", "Change encryption passphrase", self.prompt_change_passphrase),
        ]]

    def ask_secret(self, title: str, then) -> None:
        self.push_screen(TextPrompt(title, "Passphrase", password=True), lambda value: then(value) if value else None)

    def prompt_unlock(self, then=None) -> None:
        if not self.vault.has_key():
            self.notify("Encryption is not set up yet. Use Encrypt this note to start.", severity="warning")
            return
        if self.vault.cipher is not None:
            if then:
                then()
            else:
                self.notify("Encrypted notes are already unlocked.")
            return

        def unlock(passphrase: str) -> None:
            try:
                self.vault.unlock(passphrase)
            except (OSError, ValueError) as error:
                self.notify(str(error), severity="error", timeout=10)
                return
            self.refresh_notes()
            if then:
                then()
            else:
                self.notify("Encrypted notes unlocked until you lock them or quit.")

        self.ask_secret("Unlock encrypted notes", unlock)

    def encrypt_current(self) -> None:
        if self.current.encrypted:
            self.notify("This note is already encrypted.")
        elif self.vault.has_key():
            self.prompt_unlock(then=lambda: self.set_current_encryption(True))
        else:
            self.ask_secret("Choose a passphrase for encrypted notes (8+ characters). " + LOST_PASSPHRASE,
                            self.confirm_new_passphrase)

    def confirm_new_passphrase(self, passphrase: str) -> None:
        try:
            check_passphrase(passphrase)
        except EncryptionError as error:
            self.notify(str(error), severity="error")
            return
        self.ask_secret("Repeat the passphrase", lambda repeat: self.set_up_encryption(passphrase, repeat))

    def set_up_encryption(self, passphrase: str, repeat: str) -> None:
        if repeat != passphrase:
            self.notify("The passphrases did not match; encryption was not set up.", severity="error")
            return
        try:
            self.vault.setup_encryption(passphrase)
        except (OSError, ValueError) as error:
            self.notify(str(error), severity="error", timeout=10)
            return
        self.notify("Encryption is set up. Keep the passphrase somewhere safe. " + LOST_PASSPHRASE, timeout=15)
        self.set_current_encryption(True)

    def decrypt_current(self) -> None:
        if not self.current.encrypted:
            self.notify("This note is not encrypted.")
            return
        self.set_current_encryption(False)

    def set_current_encryption(self, encrypted: bool) -> None:
        if self.current.original is None:
            self.current.encrypted = encrypted
            self.dirty = True
            if not self.save_current(explicit=True):
                self.current.encrypted = not encrypted
                return
            self.notify("Note encrypted on disk. Its unencrypted saved versions were removed; backups made before "
                        "now still contain the old text." if encrypted else
                        "Encryption removed. This note is stored as plain text again.", timeout=12)
            return
        if not self.save_current(explicit=True):
            return
        try:
            note, changed = self.vault.set_encrypted(self.current.id, self.workspace, encrypted)
        except (OSError, ValueError) as error:
            self.notify(str(error), severity="error", timeout=10)
            return
        self.load(note)
        if not changed:
            self.notify("This note is already encrypted." if encrypted else "This note is not encrypted.")
            return
        self.notify("Note encrypted on disk. Its unencrypted saved versions were removed; backups made before "
                    "now still contain the old text." if encrypted else
                    "Encryption removed. This note is stored as plain text again.", timeout=12)

    def lock_notes(self) -> None:
        if self.vault.cipher is None:
            self.notify("Encrypted notes are already locked.")
            return
        if not self.save_current(explicit=True):
            return
        self.vault.lock()
        if self.current.encrypted:
            self.load(self.new_note())
        self.refresh_notes()
        self.notify("Encrypted notes locked.")

    def prompt_change_passphrase(self) -> None:
        if not self.vault.has_key():
            self.notify("Encryption is not set up yet. Use Encrypt this note to start.", severity="warning")
            return
        self.ask_secret("Current passphrase", lambda old: self.ask_secret(
            "New passphrase (8+ characters)", lambda new: self.ask_secret(
                "Repeat the new passphrase", lambda repeat: self.change_passphrase(old, new, repeat))))

    def change_passphrase(self, old: str, new: str, repeat: str) -> None:
        if new != repeat:
            self.notify("The new passphrases did not match; nothing was changed.", severity="error")
            return
        try:
            self.vault.change_passphrase(old, new)
        except (OSError, ValueError) as error:
            self.notify(str(error), severity="error", timeout=10)
            return
        self.notify("Passphrase changed.")
