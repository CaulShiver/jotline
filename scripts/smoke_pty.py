"""Exercise a real POSIX terminal session against an installed Jotline package.

Run with the isolated wheel environment's Python. This checks the terminal
protocol and persistence, not a terminal emulator or screen reader.
"""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time


def main():
    if os.name != 'posix':
        raise SystemExit('This smoke check requires POSIX PTY support')
    import fcntl
    import pty
    import struct
    import termios

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
    with tempfile.TemporaryDirectory(prefix='jotline-pty-') as folder:
        env = dict(os.environ, TERM='xterm-256color')
        process = subprocess.Popen([sys.executable, '-I', '-m', 'jotline', '--vault', folder],
                                   stdin=slave, stdout=slave, stderr=slave, env=env,
                                   start_new_session=True)
        os.close(slave)
        output = bytearray()

        def collect_until(predicate, timeout=10):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if predicate():
                    return
                if select.select([master], [], [], 0.05)[0]:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    output.extend(chunk)
                if process.poll() is not None:
                    break
            if not predicate():
                raise AssertionError('Terminal workflow timed out or exited unexpectedly')

        try:
            collect_until(lambda: b'jotline' in output)
            body = 'PTY caf\u00e9 \u65e5\u672c\u8a9e smoke'
            # Bracketed paste exercises the terminal input path without depending
            # on a desktop clipboard or IME being configured on the machine.
            os.write(master, b'\x1b[200~' + body.encode('utf-8') + b'\x1b[201~')
            collect_until(lambda: any(body in path.read_text(encoding='utf-8')
                                      for path in Path(folder).glob('*.md')))
            os.write(master, b'\x11')  # Ctrl+Q: save and quit.
            collect_until(lambda: process.poll() is not None)
            assert process.wait(timeout=2) == 0
            result = subprocess.run([sys.executable, '-I', '-m', 'jotline', '--vault', folder,
                                     'list', '--json'], capture_output=True, text=True, check=True)
            assert len(json.loads(result.stdout)) == 1
            print('POSIX PTY: startup, Unicode bracketed paste, autosave and Ctrl+Q passed.')
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            os.close(master)


if __name__ == '__main__':
    main()
