"""Validate release identity and write portable package checksums."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil


RELEASE_SCRIPTS = ('install.py', 'install.ps1')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checksums', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = (root / 'src/jotline/__init__.py').read_text(encoding='utf-8')
    version = re.search(r'^__version__ = "([^"]+)"$', source, re.MULTILINE)[1]
    tag = os.environ.get('RELEASE_TAG')
    if tag and tag != 'v' + version:
        parser.error(f'Tag {tag!r} does not match package version {version!r}')
    if args.checksums:
        distribution = root / 'dist'
        for name in RELEASE_SCRIPTS:
            shutil.copy2(root / 'scripts' / name, distribution / name)
        packages = sorted([
            *distribution.glob('*.whl'),
            *distribution.glob('*.tar.gz'),
            *(distribution / name for name in RELEASE_SCRIPTS),
        ])
        expected = {
            f'jotline-{version}-py3-none-any.whl',
            f'jotline-{version}.tar.gz',
            *RELEASE_SCRIPTS,
        }
        if {path.name for path in packages} != expected:
            parser.error('Build exactly the current wheel, source distribution and installers before publishing')
        checksums = ''.join(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n'
                            for path in packages)
        (distribution / 'SHA256SUMS').write_text(checksums, encoding='utf-8')
    print(f'Release identity verified: v{version}')


if __name__ == '__main__':
    main()
