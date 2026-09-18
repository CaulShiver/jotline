#!/usr/bin/env python3
"""Install the latest published Jotline wheel after verifying SHA256SUMS.

Linux and macOS. Python 3.11+. Git is not required, and you do not
need to hunt a wheel filename. Prefer `uv tool` or pipx when they are on PATH.
Windows is out of scope.

Examples:
  python3 install.py
  python3 install.py --from-dir dist
  python3 install.py --tag v0.9.7 --force
  python3 install.py --encryption
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request


REPO = "CaulShiver/jotline"
GITHUB_API = f"https://api.github.com/repos/{REPO}/releases"
USER_AGENT = "jotline-installer"
WHEEL_NAME = "jotline-{version}-py3-none-any.whl"
CHECKSUMS_NAME = "SHA256SUMS"
SUPPORTED = "Linux and macOS"
WINDOWS_UNSUPPORTED = "Jotline supports Linux and macOS only. Windows is out of scope."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-dir", type=Path, help="Install from a local dist directory instead of GitHub")
    parser.add_argument("--tag", help="Install this release tag instead of latest, for example v0.9.7")
    parser.add_argument("--force", action="store_true", help="Reinstall if Jotline is already present")
    parser.add_argument("--encryption", action="store_true", help="Also install the optional cryptography extra")
    parser.add_argument("--installer", choices=("uv", "pipx", "pip"),
                        help="Force an installer; default is uv, then pipx, then pip")
    parser.add_argument("--python", help="Python interpreter used with --installer pip")
    parser.add_argument("--releases-url", default=os.environ.get("JOTLINE_RELEASES_URL"),
                        help="Override the GitHub releases JSON URL (tests)")
    args = parser.parse_args(argv)
    try:
        require_python()
        if args.from_dir is not None:
            wheel, checksums = local_artifacts(args.from_dir)
            version = version_from_wheel(wheel.name)
        else:
            release = fetch_release(args.tag, args.releases_url)
            version = version_from_tag(release["tag_name"])
            wheel, checksums = download_release_artifacts(release, version)
        verify_checksum(wheel, checksums)
        installer = args.installer or detect_installer(args.python)
        install_wheel(wheel, installer=installer, python=args.python, force=args.force,
                      encryption=args.encryption)
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        print(f"Jotline install failed: {error}", file=sys.stderr)
        return 1
    print(f"Installed jotline {version} ({SUPPORTED}).")
    print("Open a terminal and run: jotline")
    print("It opens on a blank page. Type; your writing saves as local Markdown.")
    return 0


def require_python() -> None:
    if sys.platform == "win32":
        raise ValueError(WINDOWS_UNSUPPORTED)
    if sys.version_info < (3, 11):
        raise ValueError("Jotline needs Python 3.11 or newer on Linux or macOS")


def detect_installer(python: str | None) -> str:
    if python:
        return "pip"
    if shutil.which("uv"):
        return "uv"
    if shutil.which("pipx"):
        return "pipx"
    return "pip"


def version_from_tag(tag: str) -> str:
    if not tag.startswith("v") or not tag[1:].strip():
        raise ValueError(f"Release tag {tag!r} is not a Jotline version tag")
    return tag[1:]


def version_from_wheel(name: str) -> str:
    prefix, suffix = "jotline-", "-py3-none-any.whl"
    if not name.startswith(prefix) or not name.endswith(suffix):
        raise ValueError(f"Unexpected wheel name {name}")
    return name[len(prefix):-len(suffix)]


def local_artifacts(directory: Path) -> tuple[Path, str]:
    directory = directory.resolve()
    wheels = sorted(directory.glob("jotline-*-py3-none-any.whl"))
    if len(wheels) != 1:
        raise ValueError(f"Expected exactly one Jotline wheel in {directory}")
    checksums_path = directory / CHECKSUMS_NAME
    if not checksums_path.is_file():
        raise ValueError(f"Missing {CHECKSUMS_NAME} next to the wheel; refuse to install an unverified package")
    return wheels[0], checksums_path.read_text(encoding="utf-8")


def fetch_release(tag: str | None, releases_url: str | None) -> dict:
    if releases_url:
        url = releases_url
    elif tag:
        url = f"{GITHUB_API}/tags/{urllib.parse.quote(tag)}"
    else:
        url = f"{GITHUB_API}/latest"
    payload = json.loads(read_url(url, accept="application/vnd.github+json").decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("tag_name"), str):
        raise ValueError("GitHub release metadata was not a release object")
    return payload


def download_release_artifacts(release: dict, version: str) -> tuple[Path, str]:
    expected_wheel = WHEEL_NAME.format(version=version)
    wheel_asset = asset_url(release, expected_wheel)
    checksums = read_url(asset_url(release, CHECKSUMS_NAME)).decode("utf-8")
    directory = Path(tempfile.mkdtemp(prefix="jotline-install-"))
    wheel = directory / expected_wheel
    wheel.write_bytes(read_url(wheel_asset))
    return wheel, checksums


def asset_url(release: dict, name: str) -> str:
    for asset in release.get("assets") or []:
        if isinstance(asset, dict) and asset.get("name") == name:
            url = asset.get("browser_download_url")
            if isinstance(url, str) and url_allowed(url):
                return url
    raise ValueError(f"Release {release.get('tag_name')} is missing asset {name}")


def url_allowed(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme == "http" and host in {"127.0.0.1", "localhost", "::1"}:
        return True
    if parsed.scheme != "https":
        return False
    return host in {"github.com", "api.github.com"} or host.endswith(".githubusercontent.com")


def read_url(url: str, *, accept: str = "application/octet-stream") -> bytes:
    if not url_allowed(url):
        raise ValueError(f"Refusing to download from {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    with urllib.request.urlopen(request, context=ssl.create_default_context(), timeout=60) as response:
        final = response.geturl()
        if not url_allowed(final):
            raise ValueError(f"Refusing redirected download from {final}")
        return response.read()


def verify_checksum(wheel: Path, checksums: str) -> None:
    expected = checksum_for(checksums, wheel.name)
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if digest != expected:
        raise ValueError(f"Checksum mismatch for {wheel.name}: expected {expected}, got {digest}")


def checksum_for(checksums: str, filename: str) -> str:
    for line in checksums.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        digest, name = parts[0], parts[-1].lstrip("*")
        if name == filename:
            if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest.lower()):
                raise ValueError(f"Invalid SHA-256 digest for {filename}")
            return digest.lower()
    raise ValueError(f"{CHECKSUMS_NAME} has no entry for {filename}")


def install_wheel(wheel: Path, *, installer: str, python: str | None, force: bool, encryption: bool) -> None:
    if installer == "uv":
        command = ["uv", "tool", "install"]
        if force:
            command.append("--force")
        if encryption:
            command.extend(["--with", "cryptography"])
        command.append(str(wheel))
        subprocess.run(command, check=True)
        return
    if installer == "pipx":
        command = ["pipx", "install"]
        if force:
            command.append("--force")
        command.append(str(wheel))
        subprocess.run(command, check=True)
        if encryption:
            subprocess.run(["pipx", "inject", "jotline", "cryptography"], check=True)
        return
    if installer == "pip":
        target = f"{wheel}[encryption]" if encryption else str(wheel)
        python_exe = python or sys.executable
        uv = shutil.which("uv")
        if uv:
            command = [uv, "pip", "install", "--python", python_exe, "--strict"]
            if force:
                command.append("--reinstall")
            command.append(target)
        else:
            command = [python_exe, "-m", "pip", "install"]
            if force:
                command.append("--force-reinstall")
            command.append(target)
        subprocess.run(command, check=True)
        return
    raise ValueError(f"Unknown installer {installer}")


if __name__ == "__main__":
    sys.exit(main())
