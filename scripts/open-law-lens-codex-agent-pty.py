#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import os
import pty
import select
import signal
import struct
import sys
import termios
import time
import tty


def _window_size(fd: int) -> bytes:
    try:
        return fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8)
    except OSError:
        return struct.pack("HHHH", 24, 80, 0, 0)


def _set_window_size(fd: int, size: bytes) -> None:
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, size)
    except OSError:
        pass


def _build_paste(prompt: str) -> bytes:
    if not prompt.endswith("\n"):
        prompt += "\n"
    return ("\x1b[200~" + prompt + "\x1b[201~\r").encode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--startup-quiet-sec", type=float, default=2.0)
    parser.add_argument("--startup-min-sec", type=float, default=5.0)
    parser.add_argument("--no-mcp-delay-sec", type=float, default=3.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    if not args.command or args.command[0] != "--" or len(args.command) == 1:
        parser.error("pass the Codex command after --")
    command = args.command[1:]

    prompt = open(args.prompt_file, encoding="utf-8").read()
    paste = _build_paste(prompt)

    old_attrs = None
    if os.isatty(sys.stdin.fileno()):
        old_attrs = termios.tcgetattr(sys.stdin.fileno())
        tty.setraw(sys.stdin.fileno())

    pid, master_fd = pty.fork()
    if pid == 0:
        os.execvp(command[0], command)

    _set_window_size(master_fd, _window_size(sys.stdin.fileno()))

    def on_winch(_signum: int, _frame: object) -> None:
        _set_window_size(master_fd, _window_size(sys.stdin.fileno()))

    old_winch = signal.getsignal(signal.SIGWINCH)
    signal.signal(signal.SIGWINCH, on_winch)

    start = time.monotonic()
    last_mcp_output = start
    saw_mcp_startup = False
    prompt_sent = False

    try:
        while True:
            now = time.monotonic()
            if not prompt_sent:
                if saw_mcp_startup:
                    ready = (
                        now - start >= args.startup_min_sec
                        and now - last_mcp_output >= args.startup_quiet_sec
                    )
                else:
                    ready = now - start >= args.no_mcp_delay_sec
                if ready:
                    os.write(master_fd, paste)
                    prompt_sent = True

            ready, _, _ = select.select([sys.stdin.fileno(), master_fd], [], [], 0.1)
            if master_fd in ready:
                try:
                    data = os.read(master_fd, 8192)
                except OSError:
                    break
                if not data:
                    break
                if b"MCP" in data or b"mcp" in data:
                    saw_mcp_startup = True
                    last_mcp_output = time.monotonic()
                os.write(sys.stdout.fileno(), data)
            if sys.stdin.fileno() in ready:
                data = os.read(sys.stdin.fileno(), 8192)
                if not data:
                    break
                os.write(master_fd, data)
    finally:
        if old_attrs is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_attrs)
        signal.signal(signal.SIGWINCH, old_winch)

    _, status = os.waitpid(pid, 0)
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
