# Install, update and uninstall

Jotline needs Python 3.11+ and a Unicode/color terminal. It is **not published
on PyPI**. Download the wheel from the
[latest GitHub release](https://github.com/CaulShiver/jotline/releases/latest).
Git is not required. The wheel works on Linux, macOS and Windows; Python and
runtime dependencies must still be installed. `SHA256SUMS` accompanies releases.
The published asset version may lag this repository until a matching tag
finishes the release workflow; use the filename on that page, not a guessed
version.

Download `SHA256SUMS` from the same release. To display the wheel's checksum,
replace `<version>` with the version in the downloaded filename:

```sh
# Linux
sha256sum jotline-<version>-py3-none-any.whl
# macOS
shasum -a 256 jotline-<version>-py3-none-any.whl
```

In PowerShell, run
`Get-FileHash ./jotline-<version>-py3-none-any.whl -Algorithm SHA256`.
Compare the hash with the matching wheel filename in `SHA256SUMS` before
installing. Hashes verify that the file matches that release's checksum list;
they are not a separate publisher signature.

## Install

With uv, from the folder containing the downloaded wheel:

```sh
uv tool install ./jotline-<version>-py3-none-any.whl
jotline
```

Or use pipx:

```sh
pipx install ./jotline-<version>-py3-none-any.whl
jotline
```

Both commands also work in PowerShell if you use the exact filename from the
release page (`<version>` is not expanded by the shell). If the command is not
on PATH, uv and pipx often install into a user bin directory that a fresh
terminal has not picked up yet. Follow uv's `uv tool update-shell` or pipx's
`pipx ensurepath` instructions, then reopen your terminal. These tools install
Jotline in an isolated environment.

To try without either tool, create a virtual environment and install the wheel:

```sh
python -m venv jotline-env
# Linux / macOS
jotline-env/bin/python -m pip install ./jotline-<version>-py3-none-any.whl
jotline-env/bin/jotline
```

In PowerShell use `jotline-env/Scripts/python.exe` and
`jotline-env/Scripts/jotline.exe` instead. Some Unix systems name Python
`python3`; use that to create the environment if needed.

Do not run `pip install jotline` or `uv tool install jotline` without a local
wheel path: that looks up PyPI, which does not host this project.

## Update or roll back

Run `jotline backup` first and copy the archive somewhere safe. Download the
desired release's wheel and reinstall it explicitly:

```sh
uv tool install --force ./jotline-<version>-py3-none-any.whl
# Or, if installed with pipx:
pipx install --force ./jotline-<version>-py3-none-any.whl
jotline --version
jotline doctor
```

Substitute the new wheel filename when updating. A URL-based install is pinned
to that release; reinstall the new wheel rather than expecting a package-index
upgrade to locate it. Consult the changelog before rolling back across note or
settings format changes.
Version 0.8 does not understand recipes with `quote` or `restore` steps and may
load default settings instead; preserve a settings backup before downgrading.

## Uninstall

```sh
uv tool uninstall jotline
# Or:
pipx uninstall jotline
```

Uninstalling removes the app environment, not your vault. Run `jotline path`
before uninstalling to locate your notes. Keep or back up that folder; delete
it manually only if you intend to delete your notes and local backups too.

## Source development

The README retains Git-based development instructions. Source installs follow
the repository branch; use a published wheel when you want a fixed release.
`jotline --version` on a source checkout reports the in-tree package version,
which can be ahead of the latest GitHub Release assets.
