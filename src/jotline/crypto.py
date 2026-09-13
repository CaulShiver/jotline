"""Opt-in encryption for individual notes.

A random 256-bit note key encrypts note bodies with AES-GCM. The note key is
stored in the vault only after wrapping it with a key derived from the
passphrase (scrypt), so changing the passphrase rewraps one small file and
never rewrites notes. There is no recovery without the passphrase.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
import json
import os
import textwrap

KEY_FILE = ".jotline-key.json"
MARKER = "jotline-encrypted: 1"
SCRYPT_N = 2 ** 17
SCRYPT_R = 8
SCRYPT_P = 1
MAX_SCRYPT_MEMORY = 256 * 1024 * 1024
MAX_SCRYPT_WORK = 4 * SCRYPT_N * SCRYPT_R * SCRYPT_P
MIN_PASSPHRASE = 8
KEY_BYTES = 32  # AES-256 note key
SALT_BYTES = 16
NONCE_BYTES = 12  # The standard AES-GCM nonce size
TAG_BYTES = 16  # AES-GCM appends this authentication tag to every ciphertext
MISSING_LIBRARY = ("Note encryption needs the cryptography package; install it with "
                   "uv tool install 'jotline[encryption]' or pip install cryptography")
LOCKED = "This note is encrypted; unlock encrypted notes first"
_NOTE_CONTEXT = b"jotline-note-v1\0"
_KEY_CONTEXT = b"jotline-key-v1"


class EncryptionError(ValueError):
    """Encryption is unavailable, misconfigured, or a passphrase is wrong."""


def _aead(key: bytes):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise EncryptionError(MISSING_LIBRARY) from None
    return AESGCM(key)


def _invalid_tag():
    from cryptography.exceptions import InvalidTag
    return InvalidTag


def check_passphrase(passphrase: str) -> str:
    if len(passphrase) < MIN_PASSPHRASE:
        raise EncryptionError(f"Use a passphrase of at least {MIN_PASSPHRASE} characters")
    return passphrase


def _derive(passphrase: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    _check_scrypt(n, r, p)
    return hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                          maxmem=MAX_SCRYPT_MEMORY + 16 * 1024 * 1024, dklen=KEY_BYTES)


def _check_scrypt(n: int, r: int, p: int) -> None:
    # Both memory and CPU cost depend on the tuple, not individual fields.
    # Validate before passing attacker-editable key-file settings to OpenSSL.
    if (not all(type(value) is int for value in (n, r, p)) or not 2 ** 10 <= n <= 2 ** 20
            or n & (n - 1) or not 1 <= r <= 16 or not 1 <= p <= 4
            or 128 * r * (n + p + 2) > MAX_SCRYPT_MEMORY or n * r * p > MAX_SCRYPT_WORK):
        raise EncryptionError("The encryption key file has unsupported settings")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(value: object, length: int | None = None) -> bytes:
    if not isinstance(value, str):
        raise EncryptionError("The encryption key file is damaged")
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise EncryptionError("The encryption key file is damaged") from None
    if length is not None and len(data) != length:
        raise EncryptionError("The encryption key file is damaged")
    return data


@dataclass(frozen=True)
class KeyFile:
    salt: bytes
    n: int
    r: int
    p: int
    nonce: bytes
    wrapped: bytes

    @classmethod
    def create(cls, passphrase: str, note_key: bytes, *, n: int = SCRYPT_N) -> "KeyFile":
        salt, nonce = os.urandom(SALT_BYTES), os.urandom(NONCE_BYTES)
        wrapping = _derive(check_passphrase(passphrase), salt, n, SCRYPT_R, SCRYPT_P)
        return cls(salt, n, SCRYPT_R, SCRYPT_P, nonce, _aead(wrapping).encrypt(nonce, note_key, _KEY_CONTEXT))

    def unwrap(self, passphrase: str) -> bytes:
        wrapping = _derive(passphrase, self.salt, self.n, self.r, self.p)
        aead = _aead(wrapping)
        try:
            return aead.decrypt(self.nonce, self.wrapped, _KEY_CONTEXT)
        except _invalid_tag():
            raise EncryptionError("Wrong passphrase for encrypted notes") from None

    def dumps(self) -> str:
        return json.dumps({"jotline_key": 1, "kdf": "scrypt", "salt": _b64(self.salt), "n": self.n, "r": self.r,
                           "p": self.p, "cipher": "aes-256-gcm", "nonce": _b64(self.nonce),
                           "wrapped": _b64(self.wrapped)}, indent=2) + "\n"

    @classmethod
    def loads(cls, raw: str) -> "KeyFile":
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, RecursionError):
            raise EncryptionError("The encryption key file is damaged") from None
        if (not isinstance(data, dict) or data.get("jotline_key") != 1 or data.get("kdf") != "scrypt"
                or data.get("cipher") != "aes-256-gcm"):
            raise EncryptionError("The encryption key file is damaged or from a newer Jotline")
        n, r, p = data.get("n"), data.get("r"), data.get("p")
        _check_scrypt(n, r, p)
        return cls(_unb64(data.get("salt"), SALT_BYTES), n, r, p, _unb64(data.get("nonce"), NONCE_BYTES),
                   _unb64(data.get("wrapped"), KEY_BYTES + TAG_BYTES))


class NoteCipher:
    """Seals note bodies with the unlocked note key, bound to the note ID."""

    def __init__(self, note_key: bytes):
        if len(note_key) != KEY_BYTES:
            raise EncryptionError("The encryption key file is damaged")
        self._aead = _aead(note_key)

    def seal(self, note_id: str, body: str) -> str:
        nonce = os.urandom(NONCE_BYTES)
        data = nonce + self._aead.encrypt(nonce, body.encode("utf-8"), _NOTE_CONTEXT + note_id.encode("ascii"))
        return MARKER + "\n" + "\n".join(textwrap.wrap(_b64(data), 76)) + "\n"

    def open(self, note_id: str, sealed: str) -> str:
        data = sealed_bytes(sealed)
        try:
            plain = self._aead.decrypt(data[:NONCE_BYTES], data[NONCE_BYTES:], _NOTE_CONTEXT + note_id.encode("ascii"))
        except _invalid_tag():
            raise EncryptionError("Encrypted note could not be decrypted; the file is damaged or was "
                                  "encrypted with another vault's key") from None
        return plain.decode("utf-8")


def is_sealed(body: str) -> bool:
    return body.startswith(MARKER + "\n") or body.startswith(MARKER + "\r\n")


def sealed_bytes(sealed: str) -> bytes:
    if not is_sealed(sealed):
        raise EncryptionError("Encrypted note is missing its encrypted text")
    try:
        data = base64.b64decode("".join(sealed.split()[2:]), validate=True)
    except (binascii.Error, ValueError):
        raise EncryptionError("Encrypted note text is damaged") from None
    if len(data) < NONCE_BYTES + TAG_BYTES:
        raise EncryptionError("Encrypted note text is damaged")
    return data


def new_note_key() -> bytes:
    return os.urandom(KEY_BYTES)
