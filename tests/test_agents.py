"""Check the agents' permission setup against the real Claude Code and Codex CLIs.

The Codex rule and sandbox checks are free and run whenever Codex is installed.
Tests that call a model are opt-in: TANDEM_AGENT_E2E=1. They use your signed-in
CLIs and cost a fraction of a cent per run.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from support import NEOVIM_STARTUP, ROOT, clean_env, fake_agent, launches, make_repo, wait_for

README = ROOT / "README.md"
REAL_AGENTS = os.environ.get("TANDEM_AGENT_E2E") == "1"
# The leading dash checks that a prompt is never read as a command-line option.
PROMPT = ("- Use the tandem command to highlight line 3 of the code window with the note "
          "'agent check'. Do not do anything else, then reply with the word done.")
EX_PROMPT = ("Run `tandem ex vsplit other.py` to open other.py in a vertical split. Do not do anything else, "
             "then reply with the word done.")
# A command that drives the editor without the helper, as anything that can
# reach its socket could.
DIRECT_PROMPT = ("Run exactly this shell command once: nvim --server \"$TANDEM_SERVER\" --remote-expr "
                 "'execute(\"vsplit other.py\")' . Do not do anything else, then reply with the word done.")


def codex():
    """The Codex CLI itself, bypassing any shell alias or wrapper flags."""
    return shutil.which("codex")


def documented_codex_rule():
    match = re.search(r'^\s*(prefix_rule\(.*"tandem".*\))\s*$', README.read_text(), re.MULTILINE)
    assert match, "README must document the Codex prefix rule"
    return match.group(1)


def your_codex_rules_allow_tandem():
    """Whether your own ~/.codex/rules already allow the helper, which Codex loads in every test run."""
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    rules = [argument for path in sorted((home / "rules").glob("*.rules")) for argument in ("--rules", str(path))]
    if not rules:
        return False
    result = subprocess.run([codex(), "execpolicy", "check", *rules, "--", "tandem", "state"],
                            text=True, capture_output=True, timeout=30)
    return result.returncode == 0 and json.loads(result.stdout).get("decision") == "allow"


class Editor:
    """A headless Neovim with Tandem loaded, a code window, and its server in the default location."""

    def __init__(self, test):
        self.tmp = tempfile.TemporaryDirectory(prefix="at-", dir="/tmp")
        test.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name).resolve()
        self.file, _ = make_repo(self.directory)
        control = str(self.directory / "control.sock")
        self.env = clean_env(NVIM_LOG_FILE="/dev/null")
        self.proc = subprocess.Popen(
            ["nvim", "--headless", "-u", "NONE", "-i", "NONE", "-n", "--cmd", NEOVIM_STARTUP,
             "--listen", control, str(self.file)],
            cwd=self.directory, env=self.env, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        test.addCleanup(self.stop)
        self.control = control
        wait_for(lambda: Path(control).exists())
        # The plugin's own server, like a user's, lives under $TMPDIR, outside the workspace.
        self.server = self.lua("return vim.fn.serverstart()")
        self.window = self.lua("return vim.api.nvim_get_current_win()")
        self.buffer = self.lua("return vim.api.nvim_get_current_buf()")

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=5)

    def lua(self, code):
        expression = "json_encode(luaeval(%s))" % json.dumps("(function() " + code + " end)()")
        result = subprocess.run(["nvim", "--server", self.control, "--remote-expr", expression],
                                env=self.env, text=True, capture_output=True, timeout=5)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    def launch(self, command, prompt=""):
        """Runs a launch command with a stand-in agent and returns the argv and environment it got."""
        log = self.directory / "launches.jsonl"
        log.unlink(missing_ok=True)
        agent = fake_agent(self.directory / "agent", log, lifetime=0)
        self.lua("vim.g.tandem_%s_cmd = {%s}; vim.api.nvim_set_current_win(%d); vim.cmd(%s); return true"
                 % (command.lower(), json.dumps(str(agent)), self.window, json.dumps(command + " " + prompt)))
        launched = wait_for(lambda: launches(log))[0]
        self.launch_env = launched["env"]
        return launched

    def files(self):
        """The files shown in the editor's windows."""
        return self.lua("return vim.tbl_map(function(window) return vim.fs.basename(vim.api.nvim_buf_get_name("
                        "vim.api.nvim_win_get_buf(window))) end, vim.api.nvim_list_wins())")

    def notes(self):
        marks = self.lua("return vim.api.nvim_buf_get_extmarks(%d,-1,0,-1,{details=true})" % self.buffer)
        return [(mark[1] + 1, line[0][0].strip()) for mark in marks for line in mark[3].get("virt_lines", [])]


@unittest.skipUnless(codex(), "Codex is not installed")
class CodexPermissionTest(unittest.TestCase):
    def test_the_documented_rule_allows_only_the_tandem_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            rules = Path(directory) / "tandem.rules"
            rules.write_text(documented_codex_rule() + "\n")
            for command, allowed in ((["tandem", "state"], True),
                                     (["tandem", "show", "a.py", "--start", "3", "--note", "x"], True),
                                     (["tandem", "diff"], True),
                                     (["tandem", "clear"], True),
                                     # ex can run anything the editor can, so Codex asks first.
                                     (["tandem", "ex", "vsplit", "a.py"], False),
                                     (["tandemx", "state"], False),
                                     (["rm", "-rf", "x"], False)):
                with self.subTest(command=command):
                    result = subprocess.run([codex(), "execpolicy", "check", "--rules", str(rules), "--", *command],
                                            text=True, capture_output=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout).get("decision") == "allow", allowed)

    @unittest.skipUnless(shutil.which("nvim") and hasattr(os, "uname") and os.uname().sysname == "Darwin",
                         "Codex's seatbelt sandbox is macOS-only")
    def test_a_sandboxed_helper_explains_how_to_reach_the_editor(self):
        editor = Editor(self)
        env = dict(editor.launch("Codex")["env"])
        result = subprocess.run([codex(), "sandbox", "-c", 'sandbox_mode="workspace-write"', "--",
                                 "tandem", "state"],
                                env=env, cwd=editor.directory, text=True, capture_output=True, timeout=60)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rerun the same command with permission to run outside the sandbox", result.stderr)


@unittest.skipUnless(REAL_AGENTS, "Set TANDEM_AGENT_E2E=1 to run real agents")
class RealAgentTest(unittest.TestCase):
    def test_claude_reaches_the_editor_with_default_permissions(self):
        claude = self.claude()
        # Without Tandem's --settings the same request must fail, or this test proves nothing.
        for allowed in (True, False):
            with self.subTest(tandem_settings=allowed):
                editor = Editor(self)
                launched = editor.launch("Claude", PROMPT)
                argv = launched["argv"]
                if not allowed:
                    position = argv.index("--settings")
                    argv = argv[:position] + argv[position + 2:]
                result = subprocess.run(claude + argv, env=launched["env"], cwd=editor.directory,
                                        text=True, capture_output=True, timeout=300)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertEqual((3, "agent check") in editor.notes(), allowed, result.stdout)

    def claude(self):
        """The Claude command line for a test run."""
        if not shutil.which("claude"):
            self.skipTest("Claude Code is not installed")
        model = os.environ.get("TANDEM_E2E_CLAUDE_MODEL", "haiku")
        # Print mode cannot ask for approval. Skipping user settings makes this a
        # new user's setup: no personal allow rules, hooks, or bypass mode. The runs
        # stay out of your session history, though Claude still makes empty
        # folders for each run's directory in ~/.claude/projects.
        return ["claude", "-p", "--setting-sources", "project,local", "--permission-mode", "default",
                "--no-session-persistence", "--model", model, "--max-turns", "6"]

    def run_claude(self, editor, prompt, edit_settings, extra=()):
        """Runs Claude as :Claude would, with its session settings changed by edit_settings."""
        argv = list(editor.launch("Claude", prompt)["argv"])
        position = argv.index("--settings") + 1
        settings = json.loads(argv[position])
        edit_settings(settings)
        argv[position] = json.dumps(settings)
        result = subprocess.run(self.claude() + list(extra) + argv, env=editor.launch_env, cwd=editor.directory,
                                text=True, capture_output=True, timeout=300)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return result

    def test_claude_asks_before_ex_commands_unless_you_allow_them(self):
        for sandboxed in (False, True):
            for allowed in (False, True):
                with self.subTest(sandboxed=sandboxed, user_allows_ex=allowed):
                    editor = Editor(self)
                    sandbox = (lambda settings: settings["sandbox"].update(enabled=True)) if sandboxed else (lambda _: None)
                    # Print mode can't ask, so a command that needs approval is refused.
                    result = self.run_claude(editor, EX_PROMPT, sandbox,
                                             ["--allowedTools", "Bash(tandem ex *)"] if allowed else [])
                    self.assertEqual("other.py" in editor.files(), allowed, result.stdout)

    def test_claude_opens_a_split_when_asked(self):
        # What the user said, not which command to run: the instructions must
        # tell Claude that it can.
        editor = Editor(self)
        result = self.run_claude(editor, "Open other.py in a vertical split next to my code, then reply done.",
                                 lambda _: None, ["--allowedTools", "Bash(tandem ex *)"])
        self.assertIn("other.py", editor.files(), result.stdout)
        self.assertIn(editor.file.name, editor.files(), result.stdout)

    def test_claudes_sandbox_does_not_reach_the_editor(self):
        # Sandboxed commands are approved automatically, so the sandbox must not
        # reach the editor's socket, or any command could drive the editor. The
        # same command must work when the socket is open, or this test proves nothing.
        for socket_open in (False, True):
            with self.subTest(socket_open=socket_open):
                editor = Editor(self)

                def sandbox(settings):
                    settings["sandbox"]["enabled"] = True
                    if socket_open:
                        settings["sandbox"]["network"] = {"allowUnixSockets": [editor.launch_env["TANDEM_SERVER"]]}
                result = self.run_claude(editor, DIRECT_PROMPT, sandbox)
                self.assertEqual("other.py" in editor.files(), socket_open, result.stdout)

    def test_codex_reaches_the_editor_from_its_sandbox_with_the_documented_rule(self):
        if not codex():
            self.skipTest("Codex is not installed")
        model = os.environ.get("TANDEM_E2E_CODEX_MODEL")
        # Without the rule the sandbox must block the helper, or this test proves nothing.
        for allowed in (True, False):
            with self.subTest(rule=allowed):
                if not allowed and your_codex_rules_allow_tandem():
                    self.skipTest("your ~/.codex/rules already allow tandem")
                editor = Editor(self)
                launched = editor.launch("Codex", PROMPT)
                if allowed:
                    # The rule sits in a trusted project layer here instead of
                    # ~/.codex/rules, to leave your rules alone.
                    rules = editor.directory / ".codex/rules"
                    rules.mkdir(parents=True)
                    (rules / "tandem.rules").write_text(documented_codex_rule() + "\n")
                # --ephemeral keeps the session out of your Codex history. Codex
                # still adds each run's directory to the trusted projects in
                # ~/.codex/config.toml, whatever the flags.
                argv = [codex(), "exec", "--ephemeral", "--skip-git-repo-check",
                        *(["-m", model] if model else []),
                        "-c", 'sandbox_mode="workspace-write"', "-c", 'approval_policy="never"',
                        "-c", 'model_reasoning_effort="low"',
                        "-c", 'projects."%s".trust_level="trusted"' % editor.directory,
                        *launched["argv"]]
                result = subprocess.run(argv, env=launched["env"], cwd=editor.directory,
                                        text=True, capture_output=True, timeout=300)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertEqual((3, "agent check") in editor.notes(), allowed,
                                 result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
