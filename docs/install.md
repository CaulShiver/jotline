# Install, update and uninstall

Jotline needs Python 3.11+ and a Unicode/color terminal on **Linux or macOS**.
Windows is out of scope. Git is not required.

The same wheel is published for every supported OS. You do not need to hunt a
filename on the GitHub Releases page.

## PyPI

```sh
uv tool install jotline
# or
pipx install jotline
jotline
```

Optional encryption extra:

```sh
uv tool install 'jotline[encryption]'
```

## One-liner (GitHub Release)

```sh
curl -fsSL https://github.com/CaulShiver/jotline/releases/latest/download/install.py | python3
jotline
```

The installer downloads the latest release wheel and `SHA256SUMS`, verifies the
SHA-256 digest, then installs with `uv tool`, `pipx`, or `pip` (whichever it
finds). Add `--force` after the script to reinstall, or `--encryption` for the
optional cryptography extra. Pin a version with `--tag v0.9.7` (pass that after
saving `install.py` locally).

If the command is not on PATH, follow uv’s `uv tool update-shell` or pipx’s
`pipx ensurepath` instructions and reopen the terminal.

## Checksums and a named wheel

`SHA256SUMS` accompanies each GitHub Release. Download it with the wheel if you
want to verify by hand. Hashes confirm that the file matches that release’s
checksum list; they are not a separate publisher signature.

Current wheel: `jotline-0.9.7-py3-none-any.whl`

```sh
# Linux
sha256sum jotline-0.9.7-py3-none-any.whl
# macOS
shasum -a 256 jotline-0.9.7-py3-none-any.whl
```

Compare the hash with the matching filename in `SHA256SUMS` before installing.

With a downloaded wheel, from that folder:

```sh
uv tool install ./jotline-0.9.7-py3-none-any.whl
# or
pipx install ./jotline-0.9.7-py3-none-any.whl
```

To try without uv or pipx:

```sh
python -m venv jotline-env
jotline-env/bin/python -m pip install ./jotline-0.9.7-py3-none-any.whl
jotline-env/bin/jotline
```

Some Unix systems name Python `python3`.

## Update or roll back

Run `jotline backup` first and copy the archive somewhere safe. Re-run the
one-liner with `--force`, or install a specific tag:

```sh
python3 install.py --force
python3 install.py --tag v0.9.7 --force
uv tool install --force jotline
pipx install --force jotline
jotline --version
jotline doctor
```

Consult the changelog before rolling back across note or settings format
changes. Version 0.8 does not understand recipes with `quote` or `restore`
steps and may load default settings instead; preserve a settings backup before
downgrading.

## Uninstall

```sh
uv tool uninstall jotline
# or
pipx uninstall jotline
```

Uninstalling removes the app environment, not your vault. Run `jotline path`
before uninstalling to locate your notes. Keep or back up that folder; delete
it manually only if you intend to delete your notes and local backups too.

## Source development

The README retains Git-based development instructions. Source installs follow
the repository branch; use a published wheel or PyPI when you want a fixed
release.

## Platforms

Linux and macOS are the contract. Windows is out of scope. See
[supported platforms](platforms.md).
