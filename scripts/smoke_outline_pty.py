"""Exercise outliner commands through legacy POSIX terminal input bytes.

Run with the isolated wheel environment's Python. This checks the terminal
protocol and persistence, not a terminal emulator or screen reader.
"""
import errno
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
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        chunk = b''
                    if not chunk:
                        # PTY EOF can precede waitpid observing child exit.
                        # Reap within the existing deadline before checking it.
                        process.wait(timeout=max(0.001, deadline - time.monotonic()))
                        break
                    output.extend(chunk)
                if process.poll() is not None:
                    break
            if not predicate():
                raise AssertionError('Terminal workflow timed out or exited unexpectedly')

        try:
            collect_until(lambda: b'jotline' in output)
            body = '- Parent\n  - Child\n- Other'
            os.write(master, b'\x1b[200~' + body.encode() + b'\x1b[201~')
            collect_until(lambda: any(body in path.read_text(encoding='utf-8')
                                      for path in Path(folder).glob('*.md')))
            output.clear()
            os.write(master, b'\x10')  # Ctrl+P
            collect_until(lambda: b'Run a command' in output)
            os.write(master, b'outliner')
            collect_until(lambda: b'Outliner' in output)
            output.clear()
            os.write(master, b'\r')
            collect_until(lambda: b'3 blocks' in output)
            output.clear()
            os.write(master, b'\r')  # Edit the current (last) block.
            collect_until(lambda: b'Other' in output)
            os.write(master, b'\x1b[200~' + ' café'.encode() + b'\x1b[201~')
            collect_until(lambda: any('Other café' in path.read_text(encoding='utf-8')
                                      for path in Path(folder).glob('*.md')))
            output.clear()
            os.write(master, b'\x10')
            collect_until(lambda: b'Outliner commands' in output)
            output.clear()
            os.write(master, b'Insert continuation line')
            collect_until(lambda: b'Insert continuation line' in output and b'1 result' in output)
            os.write(master, b'\r')
            collect_until(lambda: any('Other café\n' in path.read_text(encoding='utf-8')
                                      for path in Path(folder).glob('*.md')))
            # No Shift+Enter encoding is needed: the menu supplies the action.
            os.write(master, b'\x1b[200~continuation\x1b[201~')
            expected = '- Parent\n  - Child\n- Other café\n  continuation'
            collect_until(lambda: any(expected in path.read_text(encoding='utf-8')
                                      for path in Path(folder).glob('*.md')))
            os.write(master, b'\x11')  # Ctrl+Q: save and quit.
            collect_until(lambda: process.poll() is not None)
            assert process.wait(timeout=2) == 0
            result = subprocess.run([sys.executable, '-I', '-m', 'jotline', '--vault', folder,
                                     'list', '--json'], capture_output=True, text=True, check=True)
            assert len(json.loads(result.stdout)) == 1
            print('Outliner PTY: command palette, inline Unicode paste, portable continuation, autosave and Ctrl+Q passed.')
        except Exception:
            Path('/tmp/jotline-outline-pty-output.bin').write_bytes(output)
            print('Synthetic notes at failure:', [path.read_text(encoding='utf-8') for path in Path(folder).glob('*.md')])
            raise
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
