"""Exercise the Vim backend headlessly; MacVim GUI tests require explicit opt-in."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid

from test_integration import CLI, ROOT


MACVIM = os.environ.get("MACVIM_BINARY", "/Applications/MacVim.app/Contents/MacOS/Vim")
TERMINAL_VIM = os.environ.get("VIM_TEST_BINARY") or shutil.which("vim")
TERMINAL_FEATURES = subprocess.run([TERMINAL_VIM, "--version"], text=True, capture_output=True).stdout if TERMINAL_VIM else ""


def vim_string(value):
    return "'" + value.replace("'", "''") + "'"


class VimBackendCases:
    def setUp(self):
        self.binary = self.editor_binary
        self.tmp = tempfile.TemporaryDirectory(prefix="mt-", dir="/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.file = self.directory / "source 'quoted' ü.py"
        self.file.write_text("\n".join("line %d" % i for i in range(1, 61)) + "\n")
        self.other = self.directory / "other.py"
        self.other.write_text("other file\nsecond line\n")
        subprocess.run(["git", "init", "-q"], cwd=self.directory, check=True)
        self.commit("baseline")
        self.server = ("NEOVIMTOUR_TEST_" + uuid.uuid4().hex[:12].upper()) if self.use_gui else str(self.directory.resolve() / "vim.sock")
        self.env = dict(os.environ, NEOVIM_TOUR_EDITOR="macvim", NEOVIM_TOUR_SERVER=self.server,
                        NEOVIM_TOUR_VIM=self.binary, NVIM="/nonexistent/outer-neovim.sock")
        if self.use_gui:
            self.env.pop("VIM_CLIENTSERVER", None)
        else:
            self.env["VIM_CLIENTSERVER"] = "socket"
        startup = "let &runtimepath=" + vim_string(str(ROOT)) + ".','.&runtimepath"
        mode = ["-g", "-f"] if self.use_gui else ["-e", "-s", "--clientserver", "socket"]
        hold = [] if self.use_gui else ["-c", "while 1 | sleep 10m | endwhile"]
        self.proc = subprocess.Popen([self.binary, *mode, "-N", "-u", "NONE", "-U", "NONE",
                                      "-i", "NONE", "-n", "--servername", self.server,
                                      "--cmd", startup, "--cmd", "set loadplugins nomore", *hold],
                                     cwd=self.directory, env=self.env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop)
        deadline = time.monotonic() + 10
        while True:
            result = subprocess.run([self.binary, "--servername", self.server, "--remote-expr", "v:servername"],
                                    env=self.env, capture_output=True, text=True, timeout=2)
            if result.returncode == 0 and self.server in result.stdout:
                break
            if self.proc.poll() is not None or time.monotonic() > deadline:
                self.fail("Vim test server did not start")
            time.sleep(0.03)
        self.source = self.expr("win_getid()")
        self.commands("execute 'edit ' . fnameescape(" + vim_string(str(self.file)) + ")")
        self.buffer = self.expr("bufnr()")
        self.commands("vertical new", "call term_start(['sh','-c','cat'],{'curwin':1})")
        self.terminal = self.expr("win_getid()")
        self.env["NEOVIM_TOUR_WINDOW"] = str(self.source)

    def stop(self):
        if self.proc.poll() is None:
            if self.use_gui:
                subprocess.run([self.binary, "--servername", self.server, "--remote-send", "<C-\\><C-N>:qa!<CR>"],
                               env=self.env, capture_output=True, timeout=3)
            else:
                self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                self.proc.wait(timeout=3)

    def expr(self, expression):
        result = subprocess.run([self.binary, "--servername", self.server, "--remote-expr",
                                 "json_encode(" + expression + ")"], env=self.env, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def commands(self, *commands):
        return self.expr("execute(json_decode(%s))" % vim_string(json.dumps(commands, ensure_ascii=False)))

    def call(self, *args, success=True):
        result = subprocess.run([str(CLI), *args], env=self.env, cwd=self.directory,
                                text=True, capture_output=True, timeout=12)
        self.assertEqual(result.returncode == 0, success, result.stderr or result.stdout)
        return json.loads(result.stdout)

    def commit(self, message):
        subprocess.run(["git", "-c", "core.autocrlf=false", "add", "."], cwd=self.directory, check=True)
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                        "commit", "-qm", message], cwd=self.directory, check=True)

    def test_state_and_read_include_unsaved_source(self):
        self.commands("call setbufline(%d,1,'not on disk')" % self.buffer)
        result = self.call("state")["result"]
        self.assertEqual(result["target"], self.source)
        self.assertEqual(result["current_window"], self.terminal)
        self.assertEqual(self.call("read", "--start", "1", "--end", "2")["result"]["lines"],
                         ["not on disk", "line 2"])

    def test_quoted_multiline_notes_are_literal(self):
        note = "O'Brien\nü \\ $HOME `touch sentinel` $(touch sentinel) ');throw 'injected"
        self.call("highlight", "2", "--note", note)
        props = self.expr("prop_list(1,{'bufnr':%d,'end_lnum':-1})" % self.buffer)
        texts = [prop["text"] for prop in props if "text" in prop]
        self.assertCountEqual(texts, ["  " + line for line in note.split("\n")])
        self.assertFalse((self.directory / "sentinel").exists())
        self.assertFalse(self.expr("getbufvar(%d,'&modified')" % self.buffer))

    def test_show_preserves_focus_buffers_options_and_autosave(self):
        self.commands("set nohidden autowrite autowriteall", "let g:leave_count=0",
                      "autocmd BufLeave,FocusLost * let g:leave_count+=1 | silent! wall",
                      "call setbufvar(%d,'&bufhidden','wipe')" % self.buffer,
                      "call setbufline(%d,1,'unsaved change')" % self.buffer)
        self.call("show", str(self.other), "--line", "2", "--note", "A tour note")
        self.assertEqual(self.expr("win_getid()"), self.terminal)
        self.assertEqual(self.expr("getcurpos(%d)[1:2]" % self.source), [2, 1])
        self.assertEqual(self.expr("g:leave_count"), 0)
        self.assertEqual(self.expr("getbufline(%d,1,1)" % self.buffer), ["unsaved change"])
        self.assertEqual(self.expr("getbufvar(%d,'&bufhidden')" % self.buffer), "wipe")
        self.assertEqual(self.expr("[&hidden,&autowrite,&autowriteall]"), [0, 1, 1])
        self.assertTrue(self.file.read_text().startswith("line 1\n"))

    def test_annotations_and_clear_preserve_text_and_other_properties(self):
        self.commands("call prop_type_add('OtherPlugin',{'highlight':'Error'})",
                      "call prop_add(1,1,{'type':'OtherPlugin','bufnr':%d,'length':1})" % self.buffer)
        self.call("show", str(self.file), "--line", "10", "--end", "15", "--note", "Tour note")
        props = self.expr("prop_list(1,{'bufnr':%d,'end_lnum':-1})" % self.buffer)
        self.assertTrue(any(p.get("text", "").strip() == "Tour note" for p in props))
        self.assertTrue(any(p["lnum"] == 15 and p["type"].startswith("NeovimTourRange") for p in props))
        self.assertFalse(self.expr("getbufvar(%d,'&modified')" % self.buffer))
        self.call("clear")
        self.assertEqual([p["type"] for p in self.expr("prop_list(1,{'bufnr':%d,'end_lnum':-1})" % self.buffer)],
                         ["OtherPlugin"])

    def test_diff_baseline_and_cleanup_preserve_unsaved_buffer(self):
        self.commands("call setbufline(%d,1,'unsaved change')" % self.buffer)
        result = self.call("diff", str(self.file))["result"]
        baseline = self.expr("getbufline(winbufnr(%d),1,'$')" % result["baseline_window"])
        self.assertEqual(baseline, ["line %d" % i for i in range(1, 61)])
        self.assertEqual(self.call("read", "--end", "1")["result"]["lines"], ["unsaved change"])
        self.assertEqual(self.expr("win_getid()"), self.terminal)
        self.assertEqual(self.expr("len(getwininfo())"), 3)
        self.call("clear")
        self.assertEqual(self.expr("len(getwininfo())"), 2)
        self.assertFalse(self.expr("getwinvar(%d,'&diff')" % self.source))
        self.assertTrue(self.expr("getbufvar(%d,'&modified')" % self.buffer))

    def test_diff_handles_crlf_and_deleted_directories(self):
        folder = self.directory / "removed"
        folder.mkdir()
        file = folder / "old.py"
        file.write_bytes(b"first\r\nsecond\r\n")
        self.commit("CRLF baseline")
        file.unlink()
        folder.rmdir()
        result = self.call("diff", str(file))["result"]
        self.assertEqual(self.expr("getbufline(winbufnr(%d),1,'$')" % result["baseline_window"]),
                         ["first", "second"])
        self.assertEqual(self.call("read")["result"]["lines"], [""])
        self.call("clear")
        self.assertFalse(file.exists())

    def test_invalid_show_and_closed_targets_leave_the_tour_in_place(self):
        result = self.call("diff", str(self.file))["result"]
        self.commands("let &eventignore='TextChanged,InsertLeave'")
        self.call("show", str(self.directory / "missing.py"), success=False)
        self.call("show", str(self.other), "--line", "999", success=False)
        self.call("--window", "999999", "state", success=False)
        self.assertEqual(self.expr("&eventignore"), "TextChanged,InsertLeave")
        self.assertEqual(self.expr("win_getid()"), self.terminal)
        self.assertNotEqual(self.expr("win_id2tabwin(%d)" % result["baseline_window"]), [0, 0])
        self.assertTrue(self.expr("getwinvar(%d,'&diff')" % self.source))

    def test_diff_rejects_unrelated_comparisons(self):
        self.commands("call win_execute(%d,'leftabove vsplit | diffthis')" % self.source)
        self.call("diff", str(self.file), success=False)
        self.assertEqual(self.expr("len(getwininfo())"), 3)
        self.assertFalse(self.expr("getwinvar(%d,'&diff')" % self.source))

    def test_shared_buffer_tours_and_global_clear_preserve_other_plugins(self):
        self.commands("call prop_type_add('OtherPlugin',{'highlight':'Error'})",
                      "call prop_add(1,1,{'type':'OtherPlugin','bufnr':%d,'length':1})" % self.buffer,
                      "call win_execute(%d,'leftabove vsplit | let g:second_source=win_getid()')" % self.source)
        second = self.expr("g:second_source")
        self.call("highlight", "3", "--note", "first tour")
        self.call("--window", str(second), "highlight", "5", "--note", "second tour")
        self.call("clear")
        properties = self.expr("prop_list(1,{'bufnr':%d,'end_lnum':-1})" % self.buffer)
        self.assertEqual([p["text"].strip() for p in properties if "text" in p], ["second tour"])
        self.commands("TourClear")
        properties = self.expr("prop_list(1,{'bufnr':%d,'end_lnum':-1})" % self.buffer)
        self.assertEqual([p["type"] for p in properties], ["OtherPlugin"])
        self.assertEqual(self.expr("win_getid()"), self.terminal)

    def test_default_diff_resolves_a_relatively_opened_buffer(self):
        self.commands("call win_execute(%d,'edit other.py')" % self.source)
        result = self.call("diff")["result"]
        self.assertEqual(Path(result["file"]).resolve(), self.other.resolve())
        self.assertEqual(self.expr("getbufline(winbufnr(%d),1,'$')" % result["baseline_window"]),
                         ["other file", "second line"])

    def test_diff_guard_checks_the_target_tab_when_the_terminal_is_elsewhere(self):
        self.commands("call win_execute(%d,'leftabove vsplit | diffthis')" % self.source,
                      "tabnew", "call term_start(['sh','-c','cat'],{'curwin':1})")
        current = self.expr("win_getid()")
        windows = self.expr("len(getwininfo())")
        self.call("diff", str(self.file), success=False)
        self.assertEqual(self.expr("len(getwininfo())"), windows)
        self.assertEqual(self.expr("win_getid()"), current)

    def test_launcher_passes_the_exact_macvim_connection_and_prompt(self):
        capture = self.directory / "launch.json"
        executable = self.directory / "fake codex"
        executable.write_text("#!/usr/bin/env python3\nimport json,os,sys\nfrom pathlib import Path\n"
                              "Path(%r).write_text(json.dumps({'argv':sys.argv[1:],'env':dict(os.environ)}))\n"
                              % str(capture))
        executable.chmod(0o755)
        if not self.use_gui:
            self.commands("unlet $VIM_CLIENTSERVER")
        self.commands("let g:neovim_tour_codex_cmd=[%s,'--no-daemon']" % vim_string(str(executable)),
                      "call win_gotoid(%d)" % self.source,
                      "Codex Explain the 'quoted' function; do not run shell commands")
        deadline = time.monotonic() + 5
        while not capture.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(capture.exists(), "Codex child did not start")
        result = json.loads(capture.read_text())
        if not self.use_gui:
            self.assertEqual(result["env"].get("VIM_CLIENTSERVER"), "socket")
        self.assertEqual(result["env"]["NEOVIM_TOUR_EDITOR"], "macvim")
        self.assertEqual(result["env"]["NEOVIM_TOUR_SERVER"], self.server)
        self.assertEqual(result["env"]["NEOVIM_TOUR_WINDOW"], str(self.source))
        self.assertEqual(Path(result["env"]["NEOVIM_TOUR_VIM"]).resolve(), Path(self.binary).resolve())
        self.assertEqual(Path(result["env"]["NEOVIM_TOUR_CLI"]).resolve(), CLI)
        self.assertEqual(result["argv"], ["--no-daemon", "Read and follow %s. Explain the 'quoted' function; do not run shell commands" % (ROOT / "skills/neovim-tour/SKILL.md")])


@unittest.skipUnless("+socketserver" in TERMINAL_FEATURES,
                     "Set VIM_TEST_BINARY to terminal Vim with +socketserver")
class TerminalVimTest(VimBackendCases, unittest.TestCase):
    editor_binary = TERMINAL_VIM
    use_gui = False


@unittest.skipUnless(os.environ.get("MACVIM_GUI_TESTS") == "1" and Path(MACVIM).is_file(),
                     "MacVim GUI tests are opt-in: MACVIM_GUI_TESTS=1")
class MacVimTest(VimBackendCases, unittest.TestCase):
    editor_binary = MACVIM
    use_gui = True


if __name__ == "__main__":
    unittest.main()
