"""Public installer and tagged-release packaging."""
from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from zipfile import ZipFile, ZipInfo

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_installer():
    spec = importlib.util.spec_from_file_location("jotline_install", ROOT / "scripts/install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INSTALL = load_installer()


def dummy_wheel(directory: Path, version: str = "0.0.0") -> Path:
    name = f"jotline-{version}-py3-none-any.whl"
    path = directory / name
    metadata = "\n".join([
        "Metadata-Version: 2.1",
        "Name: jotline",
        f"Version: {version}",
        "Summary: test wheel",
        "Requires-Python: >=3.11",
        "",
    ])
    wheel = "\n".join([
        "Wheel-Version: 1.0",
        "Generator: jotline-tests",
        "Root-Is-Purelib: true",
        "Tag: py3-none-any",
        "",
    ])
    init = "version = %r\n" % version
    record = "jotline/__init__.py,sha256=unused,0\n"
    with ZipFile(path, "w") as archive:
        for inner, data in (
            ("jotline/__init__.py", init),
            (f"jotline-{version}.dist-info/METADATA", metadata),
            (f"jotline-{version}.dist-info/WHEEL", wheel),
            (f"jotline-{version}.dist-info/RECORD", record),
        ):
            info = ZipInfo(inner)
            archive.writestr(info, data)
    return path


def write_checksums(directory: Path, *paths: Path) -> Path:
    lines = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in paths)
    checksums = directory / "SHA256SUMS"
    checksums.write_text(lines, encoding="utf-8")
    return checksums


def create_venv(directory: Path) -> Path:
    uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
    subprocess.run([uv, "venv", str(directory)], check=True)
    return directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def test_checksum_parser_accepts_gnu_and_binary_markers():
    digest = "ab" * 32
    other = "cd" * 32
    assert INSTALL.checksum_for(f"{digest}  jotline-1.0.0-py3-none-any.whl\n",
                                "jotline-1.0.0-py3-none-any.whl") == digest
    assert INSTALL.checksum_for(f"{other} *install.py\n", "install.py") == other
    with pytest.raises(ValueError, match="no entry"):
        INSTALL.checksum_for(f"{digest}  other.whl\n", "jotline-1.0.0-py3-none-any.whl")


def test_url_allowlist_accepts_github_and_loopback_only():
    assert INSTALL.url_allowed("https://github.com/CaulShiver/jotline/releases/download/v1/x")
    assert INSTALL.url_allowed("https://objects.githubusercontent.com/foo")
    assert INSTALL.url_allowed("http://127.0.0.1:9/latest")
    assert not INSTALL.url_allowed("http://evil.example/latest")
    assert not INSTALL.url_allowed("https://evil.example/latest")


def test_from_dir_refuses_a_wheel_without_checksums(tmp_path):
    dummy_wheel(tmp_path)
    with pytest.raises(ValueError, match="unverified"):
        INSTALL.local_artifacts(tmp_path)


def test_from_dir_refuses_checksum_mismatch(tmp_path):
    wheel = dummy_wheel(tmp_path)
    (tmp_path / "SHA256SUMS").write_text("0" * 64 + f"  {wheel.name}\n", encoding="utf-8")
    wheel_path, checksums = INSTALL.local_artifacts(tmp_path)
    with pytest.raises(ValueError, match="Checksum mismatch"):
        INSTALL.verify_checksum(wheel_path, checksums)


def test_from_dir_installs_verified_wheel_with_pip(tmp_path):
    wheel = dummy_wheel(tmp_path)
    write_checksums(tmp_path, wheel)
    venv = tmp_path / "venv"
    python = create_venv(venv)
    assert INSTALL.main(["--from-dir", str(tmp_path), "--python", str(python), "--installer", "pip"]) == 0
    exported = subprocess.run(
        [str(python), "-c", "import jotline; print(jotline.version)"],
        check=True, capture_output=True, text=True)
    assert exported.stdout.strip() == "0.0.0"


def test_github_latest_one_liner_downloads_and_verifies(tmp_path):
    wheel = dummy_wheel(tmp_path, "9.9.9")
    checksums = write_checksums(tmp_path, wheel)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            mapping = {
                "/latest": json.dumps({
                    "tag_name": "v9.9.9",
                    "assets": [
                        {"name": wheel.name, "browser_download_url": f"http://127.0.0.1:{self.server.server_port}/wheel"},
                        {"name": "SHA256SUMS", "browser_download_url": f"http://127.0.0.1:{self.server.server_port}/sums"},
                    ],
                }).encode(),
                "/wheel": wheel.read_bytes(),
                "/sums": checksums.read_bytes(),
            }
            body = mapping.get(self.path)
            if body is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        venv = tmp_path / "venv"
        python = create_venv(venv)
        url = f"http://127.0.0.1:{server.server_port}/latest"
        assert INSTALL.main(["--releases-url", url, "--python", str(python), "--installer", "pip"]) == 0
        listed = subprocess.run(
            [str(python), "-c", "import jotline; print(jotline.version)"],
            check=True, capture_output=True, text=True)
        assert listed.stdout.strip() == "9.9.9"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_release_assets_include_installers_for_every_os():
    source = (ROOT / "scripts/release_metadata.py").read_text(encoding="utf-8")
    assert "install.py" in source
    assert "install.ps1" in source
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "dist/install.py" in workflow
    assert "dist/install.ps1" in workflow
    assert "dist/SHA256SUMS" in workflow
    assert "gh release create" in workflow
    assert "pypa/gh-action-pypi-publish" in workflow
    assert "id-token: write" in workflow
    powershell = (ROOT / "scripts/install.ps1").read_text(encoding="utf-8")
    assert "Windows is supported" in powershell
    assert "releases/latest/download/install.py" in powershell


def test_ci_installs_through_the_public_installer_on_windows_too():
    workflow = (ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8")
    assert "windows-latest" in workflow
    assert "macos-latest" in workflow
    assert "ubuntu-latest" in workflow
    assert "python scripts/install.py --from-dir dist" in workflow
    assert "uv pip install --python \"$smoke_python\" --strict dist/*.whl" not in workflow
    release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "uses: ./.github/workflows/test.yml" in release
    assert "windows-latest" not in release.replace("test.yml", "")
    assert "Operating System :: Microsoft :: Windows" in (ROOT / "pyproject.toml").read_text()
