"""Shared size and scan budgets. Keep these out of store so filesystem helpers stay independent."""

MAX_NOTE_BYTES = 10 * 1024 * 1024
MAX_SETTINGS_BYTES = 256 * 1024
LOCK_TIMEOUT_SECONDS = 1.0
MAX_CACHE_BYTES = 32 * 1024 * 1024
MAX_CACHED_NOTES = 2048
CACHE_TTL_SECONDS = 1.0
MAX_SCAN_ENTRIES = 10_000
MAX_SCAN_BYTES = 128 * 1024 * 1024
MAX_DERIVED_ITEMS = 50_000
# Editor insertions stop this far short of the file limit so the metadata header always fits.
EDIT_LIMIT_BYTES = MAX_NOTE_BYTES - 4096
