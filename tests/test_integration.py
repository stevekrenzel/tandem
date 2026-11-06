"""Exercise the public CLI against real Neovim processes, without Python packages."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/neovim-tour/scripts/nvim-tour"


@unittest.skipUnless(shutil.which("nvim"), "Neovim is required")
class EditorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="nt-", dir="/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.file = self.directory / "source 'quoted' ü.py"
        self.file.write_text("\n".join("line %d" % i for i in range(1, 61)) + "\n")
        self.other = self.directory / "other.py"
        self.other.write_text("other file\nsecond line\n")
        for args in (["init", "-q"], ["add", "."],
                     ["-c", "user.name=Test", "-c", "user.email=test@example.com",
                      "commit", "-qm", "baseline"]):
            subprocess.run(["git", *args], cwd=self.directory, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.socket = str(self.directory / "n.sock")
        self.env = dict(os.environ, NVIM_LOG_FILE="/dev/null")
        self.env.pop("NVIM", None)
        startup = "vim.opt.runtimepath:prepend(%s); vim.o.loadplugins=true" % json.dumps(str(ROOT), ensure_ascii=False)
        self.proc = subprocess.Popen(
            ["nvim", "--headless", "-u", "NONE", "-i", "NONE", "-n",
             "--cmd", "lua " + startup, "--listen", self.socket],
            cwd=self.directory, env=self.env, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop)
        deadline = time.monotonic() + 5
        while not Path(self.socket).exists():
            if self.proc.poll() is not None or time.monotonic() > deadline:
                self.fail("Neovim did not start")
            time.sleep(0.01)
        self.source = self.lua("return vim.api.nvim_get_current_win()")
        self.lua("vim.cmd.edit(%s); return true" % json.dumps(str(self.file), ensure_ascii=False))
        self.buffer = self.lua("return vim.api.nvim_get_current_buf()")
        self.terminal = self.lua("""
            vim.cmd('vnew')
            vim.fn.jobstart({'sh', '-c', 'cat'}, {term=true})
            return vim.api.nvim_get_current_win()
        """)
        self.env.update(NVIM=self.socket, NEOVIM_TOUR_SOCKET=self.socket,
                        NEOVIM_TOUR_WINDOW=str(self.source))

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=5)

    def lua(self, code):
        expression = "json_encode(luaeval(%s))" % json.dumps("(function() " + code + " end)()", ensure_ascii=False)
        result = subprocess.run(["nvim", "--server", self.socket, "--remote-expr", expression],
                                env=self.env, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def call(self, *args, success=True):
        result = subprocess.run([sys.executable, str(CLI), *args], env=self.env,
                                cwd=self.directory, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode == 0, success, result.stderr or result.stdout)
        return json.loads(result.stdout)

    def test_show_preserves_focus_unsaved_buffers_and_autosave_hooks(self):
        self.lua("""
            vim.api.nvim_buf_set_lines(%d, 0, 1, false, {'unsaved edit'})
            vim.g.leave_count=0
            vim.api.nvim_create_autocmd({'BufLeave', 'FocusLost'}, {
                callback=function() vim.g.leave_count=vim.g.leave_count+1; vim.cmd('silent! wall') end
            })
            return true
        """ % self.buffer)
        data = self.call("show", str(self.other), "--line", "2", "--note", "Look here")
        self.assertTrue(data["ok"])
        actual = self.lua("""
            return {current=vim.api.nvim_get_current_win(),
                cursor=vim.api.nvim_win_get_cursor(%d), leaves=vim.g.leave_count,
                unsaved=vim.bo[%d].modified, text=vim.api.nvim_buf_get_lines(%d,0,1,false)}
        """ % (self.source, self.buffer, self.buffer))
        self.assertEqual(actual["current"], self.terminal)
        self.assertEqual(actual["cursor"], [2, 0])
        self.assertEqual(actual["leaves"], 0)
        self.assertTrue(actual["unsaved"])
        self.assertEqual(actual["text"], ["unsaved edit"])
        self.assertTrue(self.file.read_text().startswith("line 1\n"))

    def test_annotations_do_not_change_text_or_other_namespaces(self):
        other_ns = self.lua("""
            local ns=vim.api.nvim_create_namespace('another-plugin')
            vim.api.nvim_buf_set_extmark(%d,ns,0,0,{virt_text={{'keep me'}}})
            return ns
        """ % self.buffer)
        self.call("show", str(self.file), "--line", "10", "--end", "15", "--note", "Tour note")
        self.assertEqual(self.lua("return vim.api.nvim_get_current_win()"), self.terminal)
        self.assertFalse(self.lua("return vim.bo[%d].modified" % self.buffer))
        self.call("clear")
        marks = self.lua("return vim.api.nvim_buf_get_extmarks(%d,%d,0,-1,{})" % (self.buffer, other_ns))
        self.assertEqual(len(marks), 1)

    def test_diff_compares_unsaved_content_and_cleans_up(self):
        self.lua("vim.api.nvim_buf_set_lines(%d,0,1,false,{'unsaved change'}); return true" % self.buffer)
        data = self.call("diff", str(self.file), "--base", "HEAD")
        self.assertTrue(data["ok"])
        self.assertEqual(self.lua("return #vim.api.nvim_list_wins()"), 3)
        self.assertTrue(self.lua("return vim.wo[%d].diff" % self.source))
        self.assertEqual(self.lua("return vim.api.nvim_get_current_win()"), self.terminal)
        self.assertTrue(self.file.read_text().startswith("line 1\n"))
        self.call("clear")
        self.assertEqual(self.lua("return #vim.api.nvim_list_wins()"), 2)
        self.assertFalse(self.lua("return vim.wo[%d].diff" % self.source))
        self.assertTrue(self.lua("return vim.bo[%d].modified" % self.buffer))

    def test_read_observes_unsaved_buffer_and_state_identifies_the_code_pane(self):
        self.lua("vim.api.nvim_buf_set_lines(%d,0,1,false,{'not on disk'}); return true" % self.buffer)
        state = self.call("state")["result"]
        self.assertEqual(state["target"], self.source)
        self.assertEqual(state["current_window"], self.terminal)
        self.assertEqual(self.call("read", "--start", "1", "--end", "2")["result"]["lines"],
                         ["not on disk", "line 2"])

    def test_bad_target_and_revision_leave_the_editor_unchanged(self):
        result = self.call("--window", "999999", "state", success=False)
        self.assertIn("closed", result["error"])
        self.call("diff", "--base", "does-not-exist", success=False)
        self.assertEqual(self.lua("return #vim.api.nvim_list_wins()"), 2)
        self.assertFalse(self.lua("return vim.wo[%d].diff" % self.source))

    def test_diff_for_a_new_file_uses_an_empty_baseline(self):
        added = self.directory / "added.py"
        added.write_text("new file\n")
        self.call("diff", str(added))
        self.assertEqual(self.lua("return #vim.api.nvim_list_wins()"), 3)
        self.call("clear")
        self.assertEqual(added.read_text(), "new file\n")

    def test_targets_have_independent_annotations(self):
        self.call("highlight", "3", "--note", "first tour")
        second = self.lua("""
            local buffer=vim.fn.bufadd(%s)
            vim.fn.bufload(buffer)
            local win=vim.api.nvim_open_win(buffer,false,{split='left',win=%d})
            return {win=win,buffer=buffer}
        """ % (json.dumps(str(self.other)), self.source))
        self.call("--window", str(second["win"]), "highlight", "1", "--note", "second tour")
        self.call("clear")
        first_marks = self.lua("return vim.api.nvim_buf_get_extmarks(%d,-1,0,-1,{})" % self.buffer)
        second_marks = self.lua("return vim.api.nvim_buf_get_extmarks(%d,-1,0,-1,{})" % second["buffer"])
        self.assertEqual(first_marks, [])
        self.assertEqual(len(second_marks), 1)

    def test_launcher_passes_the_socket_window_helper_and_prompt(self):
        capture = self.directory / "launch.json"
        executable = self.directory / "fake codex"
        executable.write_text("#!/usr/bin/env python3\nimport json,os,sys\n"
                              "from pathlib import Path\n"
                              "Path(%r).write_text(json.dumps({'argv':sys.argv[1:], 'env':dict(os.environ)}))\n"
                              % str(capture))
        executable.chmod(0o755)
        self.lua("""
            require('neovim_tour').setup({codex_cmd={%s,'--no-daemon'}})
            vim.api.nvim_set_current_win(%d)
            vim.cmd([[Codex Explain the 'quoted' function; don't execute shell commands]])
            return true
        """ % (json.dumps(str(executable)), self.source))
        deadline = time.monotonic() + 5
        while not capture.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(capture.exists(), "Codex child did not start")
        launched = json.loads(capture.read_text())
        self.assertEqual(launched["env"]["NVIM"], self.socket)
        self.assertEqual(launched["env"]["NEOVIM_TOUR_SOCKET"], self.socket)
        self.assertEqual(launched["env"]["NEOVIM_TOUR_WINDOW"], str(self.source))
        self.assertEqual(Path(launched["env"]["NEOVIM_TOUR_CLI"]), CLI)
        self.assertEqual(launched["argv"], ["--no-daemon", "Use $neovim-tour. Explain the 'quoted' function; don't execute shell commands"])


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.data = self.directory / "data"
        self.skills = self.directory / "skills"
        self.bin = self.directory / "bin"

    def install(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "install.py"),
                               "--nvim-data-dir", str(self.data), "--skill-dir", str(self.skills),
                               "--bin-dir", str(self.bin), *args], text=True, capture_output=True)

    def test_install_is_idempotent_and_uninstall_only_removes_our_links(self):
        for _ in range(2):
            result = self.install()
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.skills / "neovim-tour").resolve(), ROOT / "skills/neovim-tour")
        self.assertEqual((self.data / "site/pack/neovim-tour/start/neovim-tour").resolve(), ROOT)
        self.assertEqual((self.bin / "nvim-tour").resolve(), CLI)
        (self.bin / "unrelated").write_text("keep")
        self.assertEqual(self.install("--uninstall").returncode, 0)
        self.assertEqual((self.bin / "unrelated").read_text(), "keep")
        self.assertFalse((self.skills / "neovim-tour").exists())
        self.assertTrue(ROOT.exists())

    def test_conflicts_are_reported_before_installing_anything(self):
        self.skills.mkdir()
        (self.skills / "neovim-tour").mkdir()
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)
        self.assertFalse(self.data.exists())
        self.assertFalse(self.bin.exists())


if __name__ == "__main__":
    unittest.main()
