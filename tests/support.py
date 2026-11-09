"""Shared helpers for tests that drive real editors through the tandem helper."""

import fcntl
import json
import os
from pathlib import Path
import pty
import struct
import subprocess
import termios
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/tandem/scripts/tandem"
SKILL = ROOT / "skills/tandem/SKILL.md"


def clean_env(**extra):
    """The test runner's environment without any outer editor or Tandem session."""
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("TANDEM_") and key not in ("NVIM", "VIM_SERVERNAME", "VIM_CLIENTSERVER")}
    env.update(extra)
    return env


# Startup commands that load Tandem and the editor's own runtime, but none of
# the user's plugins, which would otherwise load with 'loadplugins'.
NEOVIM_STARTUP = ("lua vim.o.packpath = ''; vim.o.runtimepath = table.concat({%s, vim.env.VIMRUNTIME, "
                  "vim.fn.fnamemodify(vim.v.progpath, ':h:h') .. '/lib/nvim'}, ','); vim.o.loadplugins = true"
                  % json.dumps(str(ROOT), ensure_ascii=False))
VIM_STARTUP = ("let &runtimepath = '%s,' . $VIMRUNTIME | set packpath= loadplugins nomore"
               % str(ROOT).replace("'", "''"))


def git(directory, *args):
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                    "-c", "core.autocrlf=false", *args],
                   cwd=directory, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def make_repo(directory):
    """Creates a committed repository with a 60-line file and a short one."""
    source = directory / "source 'quoted' ü.py"
    source.write_text("".join("line %d\n" % i for i in range(1, 61)))
    other = directory / "other.py"
    other.write_text("other file\nsecond line\n")
    git(directory, "init", "-q")
    git(directory, "add", ".")
    git(directory, "commit", "-qm", "baseline")
    return source, other


def fake_agent(path, log, lifetime=60, exit_code=0):
    """Writes an agent that logs its argv and environment, then waits and exits."""
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys, time\n"
        "with open(%r, 'a') as log:\n"
        "    log.write(json.dumps({'argv': sys.argv[1:], 'env': dict(os.environ)}) + '\\n')\n"
        "time.sleep(%r)\n"
        "sys.exit(%d)\n" % (str(log), lifetime, exit_code))
    path.chmod(0o755)
    return path


def launches(log):
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def wait_for(predicate, timeout=5, message="condition was not met"):
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError(message)
        time.sleep(0.02)


def instructions(mode):
    """The system prompt that the launcher gives Claude."""
    text = SKILL.read_text().split("\n---\n", 1)[1]
    return text.strip() + "\n\nSession mode: %s." % mode


def default_ask(mode):
    return "Inspect the code window and ask what I want to %s" % ("explore." if mode == "tour" else "work on.")


class Screen:
    """Attaches a real terminal UI to a Neovim server so that it draws a screen."""

    def __init__(self, socket, rows=30, columns=100):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))
        self.process = subprocess.Popen(
            ["nvim", "--remote-ui", "--server", socket], stdin=slave, stdout=slave, stderr=slave,
            env=clean_env(TERM="xterm-256color"), start_new_session=True)
        os.close(slave)
        self.master = master
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self):
        try:
            while os.read(self.master, 65536):
                pass
        except OSError:
            pass

    def close(self):
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
        os.close(self.master)
