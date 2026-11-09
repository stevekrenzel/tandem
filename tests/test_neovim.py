"""Drive the tandem helper and launch commands against real headless Neovim processes."""

import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

from support import (CLI, NEOVIM_STARTUP, ROOT, SKILL, Screen, clean_env, default_ask, fake_agent, git,
                     instructions, launches, make_repo, wait_for)


@unittest.skipUnless(shutil.which("nvim"), "Neovim is required")
class NeovimTest(unittest.TestCase):
    def setUp(self):
        # Unix socket paths are short, so keep the directory near the root.
        self.tmp = tempfile.TemporaryDirectory(prefix="nt-", dir="/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.file, self.other = make_repo(self.directory)
        self.socket = str(self.directory / "n.sock")
        self.env = clean_env(NVIM_LOG_FILE="/dev/null")
        self.proc = subprocess.Popen(
            ["nvim", "--headless", "-u", "NONE", "-i", "NONE", "-n",
             "--cmd", NEOVIM_STARTUP, "--listen", self.socket],
            cwd=self.directory, env=self.env, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop)
        wait_for(lambda: Path(self.socket).exists() or self.proc.poll() is not None)
        self.assertIsNone(self.proc.poll(), "Neovim did not start")
        self.source = self.lua("return vim.api.nvim_get_current_win()")
        self.lua("vim.cmd.edit(%s); return true" % json.dumps(str(self.file), ensure_ascii=False))
        self.buffer = self.lua("return vim.api.nvim_get_current_buf()")
        self.terminal = self.lua("""
            vim.cmd('vnew')
            vim.fn.jobstart({'sh', '-c', 'cat'}, {term=true})
            return vim.api.nvim_get_current_win()
        """)
        self.env.update(TANDEM_SERVER=self.socket, TANDEM_WINDOW=str(self.source))
        self.log = self.directory / "launches.jsonl"

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
        result = subprocess.run([str(CLI), *args], env=self.env,
                                cwd=self.directory, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode == 0, success, result.stderr or result.stdout)
        return json.loads(result.stdout)

    def marks(self, buffer=None):
        return self.lua("return vim.api.nvim_buf_get_extmarks(%d,-1,0,-1,{details=true})" % (buffer or self.buffer))

    def windows(self):
        return self.lua("return vim.api.nvim_list_wins()")

    def agent(self, name="fake agent", **behavior):
        return fake_agent(self.directory / name, self.log, **behavior)

    def configure(self, **options):
        self.lua("require('tandem').setup(vim.json.decode(%s)); return true" % json.dumps(json.dumps(options)))

    def launch(self, command, window=None):
        """Runs a launch command as the user would. Any uncaught error fails the test."""
        return self.lua("""
            vim.api.nvim_set_current_win(%d)
            vim.v.errmsg = ''
            vim.cmd(%s)
            return {window=vim.api.nvim_get_current_win(), buffer=vim.api.nvim_get_current_buf(), error=vim.v.errmsg}
        """ % (window or self.source, json.dumps(command)))

    # ------------------------------------------------------------ helper

    def test_helper_needs_no_python_and_preserves_quoted_multiline_arguments(self):
        tools = self.directory / "tools"
        tools.mkdir()
        for tool in ("nvim", "bash"):
            (tools / tool).symlink_to(shutil.which(tool))
        self.env["PATH"] = str(tools)
        self.lua("vim.cmd('cd /tmp'); return true")
        note = "O'Brien\n\tü \\ $HOME `touch sentinel` $(touch sentinel) ');throw 'injected\n"
        self.call("show", self.file.name, "--start", "2", "--note", note)
        annotation = next(mark for mark in self.marks() if "virt_lines" in mark[3])
        self.assertEqual([line[0][0] for line in annotation[3]["virt_lines"]],
                         ["  " + line for line in note.split("\n")])
        self.assertFalse((self.directory / "sentinel").exists())

    def test_unresponsive_editor_times_out_and_can_resume(self):
        self.env["TANDEM_TIMEOUT"] = "1"
        self.proc.send_signal(signal.SIGSTOP)
        started = time.monotonic()
        try:
            result = subprocess.run([str(CLI), "state"], env=self.env, cwd=self.directory,
                                    text=True, capture_output=True, timeout=10)
        finally:
            self.proc.send_signal(signal.SIGCONT)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not answer within 1s", result.stderr)
        self.assertLess(time.monotonic() - started, 5)
        self.assertTrue(self.call("state")["ok"])

    def test_helper_falls_back_to_the_editor_on_path(self):
        self.env["TANDEM_EDITOR_BIN"] = str(self.directory / "upgraded-away" / "nvim")
        self.assertTrue(self.call("state")["ok"])

    def test_unreachable_editor_explains_sandbox_and_restart(self):
        self.env["TANDEM_SERVER"] = str(self.directory / "missing.sock")
        result = subprocess.run([str(CLI), "state"], env=self.env, cwd=self.directory,
                                text=True, capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("If this shell is sandboxed", result.stderr)
        self.assertIn("restart :Claude or :Codex", result.stderr)

    def test_malformed_commands_preserve_existing_comparison_and_annotations(self):
        self.call("diff")
        self.call("highlight", "--start", "2", "--note", "keep this stop")
        snapshot = "return {wins=vim.api.nvim_list_wins(), marks=vim.api.nvim_buf_get_extmarks(%d,-1,0,-1,{details=true})}" % self.buffer
        before = self.lua(snapshot)
        commands = [("unknown",), ("state", "--start", "1"), ("read", "--end"), ("read", "--start", "abc"),
                    ("show", str(self.other), "--start", "0"), ("show", str(self.other), "--line", "2"),
                    ("highlight",), ("highlight", "2"), ("diff", str(self.file), str(self.other)),
                    ("clear", "extra"), ("show",)]
        for command in commands:
            with self.subTest(command=command):
                self.assertIn("error", self.call(*command, success=False))
                self.assertEqual(self.lua(snapshot), before)
                self.assertEqual(self.lua("return vim.api.nvim_get_current_win()"), self.terminal)

    def test_special_files_are_rejected_before_loading(self):
        pipe = self.directory / "pipe"
        os.mkfifo(pipe)
        result = self.call("show", str(pipe), success=False)
        self.assertIn("Not a regular file", result["error"])
        self.assertEqual(self.lua("return vim.api.nvim_win_get_buf(%d)" % self.source), self.buffer)

    def test_failed_show_leaves_no_buffer_behind(self):
        before = self.lua("return #vim.fn.getbufinfo()")
        self.assertIn("does not exist", self.call("show", "missing.py", success=False)["error"])
        self.assertEqual(self.lua("return #vim.fn.getbufinfo()"), before)

    # -------------------------------------------------------- state, read

    def test_read_observes_unsaved_buffer_and_state_identifies_the_code_window(self):
        self.lua("vim.api.nvim_buf_set_lines(%d,0,1,false,{'not on disk'}); return true" % self.buffer)
        state = self.call("state")["result"]
        self.assertEqual(state["target"], self.source)
        self.assertEqual(state["current_window"], self.terminal)
        self.assertEqual(state["focus"], "other")
        self.assertEqual(Path(state["context"]["file"]).resolve(), self.file.resolve())
        self.assertTrue(state["context"]["modified"])
        read = self.call("read", "--start", "1", "--end", "2")["result"]
        self.assertEqual(read["lines"], ["not on disk", "line 2"])
        self.assertEqual((read["start"], read["end"]), (1, 2))

    def test_state_reports_one_based_cursor_and_user_focus(self):
        self.lua("vim.api.nvim_win_set_cursor(%d, {3, 4}); vim.api.nvim_set_current_win(%d); return true"
                 % (self.source, self.source))
        state = self.call("state")["result"]
        self.assertEqual(state["cursor"], [3, 5])
        self.assertEqual(state["focus"], "code")
        self.assertEqual(state["mode"], "n")

    def test_requests_work_while_the_user_is_in_another_tab(self):
        self.lua("""
            vim.api.nvim_win_call(%d, function() vim.cmd('lcd /usr') end)
            local other = vim.api.nvim_open_win(%d, false, {split='left', win=%d})
            vim.api.nvim_win_call(other, function() vim.cmd('diffthis') end)
            vim.cmd('tabnew')
            return true
        """ % (self.source, self.buffer, self.source))
        state = self.call("state")["result"]
        self.assertEqual((state["cwd"], state["focus"]), ("/usr", "other"))
        self.assertIn("diff open", self.call("diff", str(self.file), success=False)["error"])

    def test_read_returns_other_files_without_moving_the_view(self):
        self.lua("""
            local buffer = vim.fn.bufadd(%s)
            vim.fn.bufload(buffer)
            vim.api.nvim_buf_set_lines(buffer, 0, 1, false, {'unsaved other'})
            return true
        """ % json.dumps(str(self.other)))
        live = self.call("read", "other.py")["result"]
        self.assertEqual(live["lines"], ["unsaved other", "second line"])
        self.assertTrue(live["modified"])
        disk = self.directory / "disk.py"
        disk.write_text("only on disk\n")
        self.assertEqual(self.call("read", "disk.py")["result"]["lines"], ["only on disk"])
        self.assertEqual(self.lua("return vim.api.nvim_win_get_buf(%d)" % self.source), self.buffer)
        self.assertFalse(self.lua("return vim.fn.bufexists(%s) == 1" % json.dumps(str(disk))))

    def test_files_that_are_not_utf8_read_as_latin1(self):
        (self.directory / "latin1.txt").write_bytes(b"caf\xe9\n")
        self.assertEqual(self.call("read", "latin1.txt")["result"]["lines"], ["caf\u00e9"])

    def test_commands_reload_files_changed_on_disk_but_keep_unsaved_buffers(self):
        self.file.write_text("agent edit\n" + self.file.read_text())
        later = time.time() + 5
        os.utime(self.file, (later, later))
        result = self.call("show", str(self.file), "--start", "1", "--end", "2")["result"]
        self.assertEqual(result["end"], 2)
        self.assertEqual(self.lua("return vim.api.nvim_buf_get_lines(%d,0,2,false)" % self.buffer),
                         ["agent edit", "line 1"])
        self.assertFalse(self.lua("return vim.bo[%d].modified" % self.buffer))

        self.lua("vim.api.nvim_buf_set_lines(%d,0,1,false,{'user edit'}); return true" % self.buffer)
        self.file.write_text("second agent edit\n")
        os.utime(self.file, (later + 5, later + 5))
        self.assertEqual(self.call("read", "--end", "1")["result"]["lines"], ["user edit"])
        self.assertTrue(self.lua("return vim.bo[%d].modified" % self.buffer))
        self.assertEqual(self.file.read_text(), "second agent edit\n")

    # ------------------------------------------------- show, highlight

    def test_show_preserves_focus_unsaved_buffers_and_autosave_hooks(self):
        self.lua("""
            vim.api.nvim_buf_set_lines(%d, 0, 1, false, {'unsaved edit'})
            vim.g.leave_count=0
            vim.api.nvim_create_autocmd({'BufLeave', 'FocusLost'}, {
                callback=function() vim.g.leave_count=vim.g.leave_count+1; vim.cmd('silent! wall') end
            })
            return true
        """ % self.buffer)
        data = self.call("show", str(self.other), "--start", "2", "--note", "Look here")
        self.assertEqual(Path(data["result"]["file"]).resolve(), self.other.resolve())
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

    def test_a_file_with_a_swap_file_opens_read_only(self):
        swaps = self.directory / "swap"
        swaps.mkdir()
        # A crashed session leaves its swap file behind, with a change the user never saved.
        crashed = subprocess.Popen(
            ["nvim", "--headless", "-u", "NONE", "-i", "NONE", "--cmd", "set directory=%s//" % swaps, "other.py",
             "-c", "call setline(1, 'unsaved') | preserve"],
            cwd=self.directory, env=clean_env(), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_for(lambda: any(swaps.iterdir()), message="the other editor made no swap file")
        crashed.kill()
        crashed.wait()
        self.lua("vim.o.directory = %s; vim.o.updatecount = 200; return true" % json.dumps(str(swaps) + "//"))
        self.call("show", "other.py")
        buffer = self.lua("return vim.api.nvim_win_get_buf(%d)" % self.source)
        self.assertEqual(self.lua("return vim.api.nvim_buf_get_lines(%d,0,-1,false)" % buffer),
                         ["other file", "second line"])
        self.assertTrue(self.lua("return vim.bo[%d].readonly" % buffer))

    def test_show_without_a_range_opens_the_file_without_highlighting(self):
        result = self.call("show", "other.py")["result"]
        self.assertEqual(list(result), ["file"])
        self.assertEqual(Path(result["file"]).resolve(), self.other.resolve())
        other = self.lua("return vim.api.nvim_win_get_buf(%d)" % self.source)
        self.assertEqual(self.marks(other), [])

    def test_annotations_do_not_change_text_or_other_namespaces(self):
        other_ns = self.lua("""
            local ns=vim.api.nvim_create_namespace('another-plugin')
            vim.api.nvim_buf_set_extmark(%d,ns,0,0,{virt_text={{'keep me'}}})
            return ns
        """ % self.buffer)
        self.call("show", str(self.file), "--start", "10", "--end", "15", "--note", "Tour note")
        self.assertEqual(self.lua("return vim.api.nvim_get_current_win()"), self.terminal)
        self.assertFalse(self.lua("return vim.bo[%d].modified" % self.buffer))
        annotation = next(mark for mark in self.marks() if "virt_lines" in mark[3])
        self.assertEqual(annotation[1], 9)
        self.assertEqual(annotation[3]["end_row"], 15)
        self.assertEqual(annotation[3]["virt_lines"][0][0][0], "  Tour note")
        self.call("clear")
        marks = self.lua("return vim.api.nvim_buf_get_extmarks(%d,%d,0,-1,{})" % (self.buffer, other_ns))
        self.assertEqual(len(marks), 1)

    def test_a_note_on_the_first_line_is_drawn_on_screen(self):
        screen = Screen(self.socket)
        self.addCleanup(screen.close)
        wait_for(lambda: self.lua("return #vim.api.nvim_list_uis()") == 1)
        self.call("show", str(self.file), "--start", "1", "--note", "FIRST LINE NOTE")
        rows = self.lua("""
            vim.cmd('redraw!')
            local rows = {}
            for row = 1, vim.o.lines do
                local cells = {}
                for column = 1, vim.o.columns do cells[#cells + 1] = vim.fn.screenstring(row, column) end
                rows[#rows + 1] = table.concat(cells)
            end
            return rows
        """)
        note = next((i for i, row in enumerate(rows) if "FIRST LINE NOTE" in row), None)
        first = next(i for i, row in enumerate(rows) if re.search(r"line 1(?!\d)", row))
        self.assertIsNotNone(note, "\n".join(rows))
        self.assertEqual(note, first - 1)

    def test_navigation_waits_while_the_user_types_in_the_code_window(self):
        self.lua("vim.api.nvim_set_current_win(%d); return true" % self.source)
        # Insert mode, a half-typed command line, and a pending operator.
        for keys in ("i", ":%d", "d"):
            with self.subTest(keys=keys):
                subprocess.run(["nvim", "--server", self.socket, "--remote-send", keys], env=self.env, check=True)
                wait_for(lambda: self.lua("return vim.fn.mode(1)") != "n")
                for command in (("show", "other.py"), ("highlight", "--start", "2"), ("diff",)):
                    self.assertIn("typing", self.call(*command, success=False)["error"])
                self.assertEqual(self.call("read", "--end", "1")["result"]["lines"], ["line 1"])
                subprocess.run(["nvim", "--server", self.socket, "--remote-send", "<Esc>"], env=self.env, check=True)
                wait_for(lambda: self.lua("return vim.fn.mode(1)") == "n")
        self.assertEqual(self.lua("return vim.api.nvim_win_get_buf(%d)" % self.source), self.buffer)
        self.call("show", "other.py")

    def test_navigation_restores_existing_eventignore_even_after_errors(self):
        for original in ("TextChanged,InsertLeave", "all"):
            with self.subTest(eventignore=original):
                self.lua("vim.o.eventignore=%s; return true" % json.dumps(original))
                self.call("show", str(self.file), "--start", "1")
                self.assertEqual(self.lua("return vim.o.eventignore"), original)
                self.call("show", str(self.file), "--start", "999", success=False)
                self.assertEqual(self.lua("return vim.o.eventignore"), original)
                self.assertEqual(self.lua("return vim.api.nvim_get_current_win()"), self.terminal)

    def test_show_does_not_autowrite_when_hidden_buffers_are_disabled(self):
        self.lua("""
            vim.o.hidden=false
            vim.o.autowrite=true
            vim.o.autowriteall=true
            vim.api.nvim_buf_set_lines(%d,0,1,false,{'do not save me'})
            return true
        """ % self.buffer)
        self.call("show", str(self.other))
        self.assertTrue(self.file.read_text().startswith("line 1\n"))
        self.assertTrue(self.lua("return vim.bo[%d].modified" % self.buffer))
        self.assertEqual(self.lua("return {vim.o.hidden,vim.o.autowrite,vim.o.autowriteall}"),
                         [False, True, True])

    def test_show_preserves_buffers_with_destructive_bufhidden_settings(self):
        for setting in ("unload", "delete", "wipe"):
            with self.subTest(bufhidden=setting):
                file = self.directory / (setting + ".py")
                file.write_text("saved\n")
                self.call("show", str(file))
                buffer = self.lua("return vim.api.nvim_win_get_buf(%d)" % self.source)
                self.lua("vim.bo[%d].bufhidden=%s; vim.api.nvim_buf_set_lines(%d,0,-1,false,{'unsaved'}); return true"
                         % (buffer, json.dumps(setting), buffer))
                self.call("show", str(self.other))
                self.assertTrue(self.lua("return vim.api.nvim_buf_is_loaded(%d)" % buffer))
                self.assertEqual(self.lua("return vim.api.nvim_buf_get_lines(%d,0,-1,false)" % buffer), ["unsaved"])
                self.assertEqual(self.lua("return vim.bo[%d].bufhidden" % buffer), setting)
                self.assertEqual(file.read_text(), "saved\n")

    def test_invalid_show_preserves_the_current_file_and_annotations(self):
        self.call("show", str(self.file), "--start", "3", "--note", "keep this stop")
        before = self.marks()
        self.call("show", str(self.directory / "missing.py"), success=False)
        self.call("show", str(self.other), "--start", "999", success=False)
        self.assertEqual(self.lua("return vim.api.nvim_win_get_buf(%d)" % self.source), self.buffer)
        self.assertEqual(self.marks(), before)
        self.assertEqual(self.lua("return vim.api.nvim_win_get_cursor(%d)" % self.source), [3, 0])

    def test_targets_have_independent_annotations(self):
        self.call("highlight", "--start", "3", "--note", "first tour")
        second = self.lua("""
            local buffer=vim.fn.bufadd(%s)
            vim.fn.bufload(buffer)
            local win=vim.api.nvim_open_win(buffer,false,{split='left',win=%d})
            return {win=win,buffer=buffer}
        """ % (json.dumps(str(self.other)), self.source))
        self.call("--window", str(second["win"]), "highlight", "--start", "1", "--note", "second tour")
        self.call("clear")
        self.assertEqual(self.marks(), [])
        self.assertEqual(len(self.marks(second["buffer"])), 1)

    def test_closing_a_code_window_clears_its_annotations(self):
        self.call("highlight", "--start", "3", "--note", "temporary")
        self.lua("vim.api.nvim_win_close(%d, true); return true" % self.source)
        wait_for(lambda: self.marks() == [], message="annotations stayed after the window closed")
        self.assertIn("closed", self.call("state", success=False)["error"])

    # --------------------------------------------------------------- diff

    def test_git_comparison_does_not_use_the_configured_shell(self):
        self.lua("vim.o.shell='/usr/bin/false'; return true")
        self.assertTrue(self.call("diff")["ok"])

    def test_git_warnings_stay_out_of_the_baseline(self):
        self.lua("vim.env.GIT_TRACE = '1'; return true")
        result = self.call("diff")["result"]
        baseline = self.lua("return vim.api.nvim_buf_get_lines(vim.api.nvim_win_get_buf(%d),0,-1,false)"
                            % result["baseline_window"])
        self.assertEqual(baseline, ["line %d" % i for i in range(1, 61)])

    def test_diff_compares_unsaved_content_and_cleans_up(self):
        self.lua("vim.api.nvim_buf_set_lines(%d,0,1,false,{'unsaved change'}); return true" % self.buffer)
        data = self.call("diff", str(self.file), "--base", "HEAD")
        baseline = self.lua("return vim.api.nvim_buf_get_lines(vim.api.nvim_win_get_buf(%d),0,-1,false)"
                            % data["result"]["baseline_window"])
        self.assertEqual(baseline, ["line %d" % i for i in range(1, 61)])
        self.assertTrue(data["result"]["modified"])
        self.assertEqual(self.call("read", "--start", "1", "--end", "1")["result"]["lines"], ["unsaved change"])
        self.assertEqual(len(self.windows()), 3)
        self.assertTrue(self.lua("return vim.wo[%d].diff" % self.source))
        self.assertEqual(self.lua("return vim.api.nvim_get_current_win()"), self.terminal)
        self.assertTrue(self.file.read_text().startswith("line 1\n"))
        self.call("clear")
        self.assertEqual(len(self.windows()), 2)
        self.assertFalse(self.lua("return vim.wo[%d].diff" % self.source))
        self.assertTrue(self.lua("return vim.bo[%d].modified" % self.buffer))

    def test_diff_is_side_by_side_only_when_both_sides_fit(self):
        for columns, layout in ((100, "col"), (400, "row")):
            with self.subTest(columns=columns):
                self.lua("vim.o.columns = %d; vim.cmd('wincmd ='); return true" % columns)
                baseline = self.call("diff")["result"]["baseline_window"]
                parent = self.lua("""
                    local function find(node, parent)
                        if node[1] == 'leaf' then return node[2] == %d and parent or nil end
                        for _, child in ipairs(node[2]) do
                            local found = find(child, node[1])
                            if found then return found end
                        end
                    end
                    return find(vim.fn.winlayout(), nil)
                """ % baseline)
                self.assertEqual(parent, layout)
                self.call("clear")

    def test_closing_the_code_window_beside_its_comparison_cleans_up(self):
        self.lua("vim.api.nvim_win_close(%d, true); return true" % self.terminal)
        self.call("diff")
        self.lua("vim.v.errmsg = ''; vim.api.nvim_win_close(%d, true); return true" % self.source)
        comparisons = "return #vim.tbl_filter(function(b) return vim.api.nvim_buf_get_name(b):match('^tandem://') end, vim.api.nvim_list_bufs())"
        wait_for(lambda: self.lua(comparisons) == 0, message="the comparison stayed open")
        self.assertEqual(self.lua("return vim.v.errmsg"), "")

    def test_closing_the_comparison_pane_ends_the_comparison(self):
        baseline = self.call("diff")["result"]["baseline_window"]
        self.lua("vim.api.nvim_win_close(%d, true); return true" % baseline)
        wait_for(lambda: not self.lua("return vim.wo[%d].diff" % self.source),
                 message="the code window stayed in diff mode")
        self.assertTrue(self.call("diff")["ok"])

    def test_bad_target_and_revision_leave_the_editor_unchanged(self):
        self.assertIn("closed", self.call("--window", "999999", "state", success=False)["error"])
        self.call("diff", "--base", "does-not-exist", success=False)
        self.assertEqual(len(self.windows()), 2)
        self.assertFalse(self.lua("return vim.wo[%d].diff" % self.source))

    def test_diff_for_a_new_file_uses_an_empty_baseline(self):
        added = self.directory / "added.py"
        added.write_text("new file\n")
        data = self.call("diff", str(added))["result"]
        self.assertEqual(self.lua("return vim.api.nvim_buf_get_lines(vim.api.nvim_win_get_buf(%d),0,-1,false)"
                                  % data["baseline_window"]), [""])
        self.assertEqual(len(self.windows()), 3)
        self.call("clear")
        self.assertEqual(added.read_text(), "new file\n")

    def test_diff_uses_the_requested_earlier_revision(self):
        self.file.write_text("new HEAD version\n")
        git(self.directory, "commit", "-qam", "change saved version")
        self.lua("vim.api.nvim_buf_set_lines(%d,0,-1,false,{'live unsaved version'}); return true" % self.buffer)
        result = self.call("diff", str(self.file), "--base", "HEAD^")["result"]
        baseline = self.lua("return vim.api.nvim_buf_get_lines(vim.api.nvim_win_get_buf(%d),0,1,false)"
                            % result["baseline_window"])
        self.assertEqual(baseline, ["line 1"])
        self.assertEqual(self.call("read", "--end", "1")["result"]["lines"], ["live unsaved version"])

    def test_crlf_baseline_matches_neovims_live_buffer_representation(self):
        self.file.write_bytes(b"first\r\nsecond\r\n")
        git(self.directory, "commit", "-qam", "CRLF source")
        self.lua("vim.api.nvim_win_call(%d,function() vim.cmd('edit!') end); return true" % self.source)
        result = self.call("diff", str(self.file))["result"]
        baseline = self.lua("return vim.api.nvim_buf_get_lines(vim.api.nvim_win_get_buf(%d),0,-1,false)"
                            % result["baseline_window"])
        self.assertEqual(baseline, ["first", "second"])
        self.assertEqual(self.call("read")["result"]["lines"], ["first", "second"])

    def test_diff_does_not_join_an_unrelated_comparison_in_the_same_tab(self):
        other = self.lua("""
            local win=vim.api.nvim_open_win(%d,false,{split='left',win=%d})
            vim.api.nvim_win_call(win,function() vim.cmd('diffthis') end)
            return win
        """ % (self.buffer, self.source))
        result = self.call("diff", str(self.file), success=False)
        self.assertIn("diff open", result["error"])
        self.assertEqual(len(self.windows()), 3)
        self.assertTrue(self.lua("return vim.wo[%d].diff" % other))
        self.assertFalse(self.lua("return vim.wo[%d].diff" % self.source))

    def test_diff_handles_a_deleted_file_with_a_deleted_parent_directory(self):
        folder = self.directory / "removed_folder"
        folder.mkdir()
        file = folder / "removed.py"
        file.write_text("removed code\n")
        git(self.directory, "add", ".")
        git(self.directory, "commit", "-qm", "add removed file")
        file.unlink()
        folder.rmdir()
        result = self.call("diff", str(file))["result"]
        baseline = self.lua("return vim.api.nvim_buf_get_lines(vim.api.nvim_win_get_buf(%d),0,-1,false)"
                            % result["baseline_window"])
        self.assertEqual(baseline, ["removed code"])
        self.assertEqual(self.call("read")["result"]["lines"], [""])
        self.call("clear")
        self.assertFalse(file.exists())

    def test_invalid_show_preserves_the_current_comparison(self):
        result = self.call("diff", str(self.file))["result"]
        self.call("show", str(self.other), "--start", "999", success=False)
        self.assertTrue(self.lua("return vim.api.nvim_win_is_valid(%d)" % result["baseline_window"]))
        self.assertTrue(self.lua("return vim.wo[%d].diff" % self.source))
        self.assertEqual(len(self.windows()), 3)

    # ------------------------------------------------------------- launch

    def test_launchers_pass_the_connection_instructions_and_literal_prompt(self):
        agent = self.agent()
        self.configure(codex_cmd=[str(agent), "--codex-flag"], claude_cmd=[str(agent), "--claude-flag"])
        for agent_name in ("codex", "claude"):
            for mode in ("partner", "tour"):
                for topic in ("", "Explain the 'quoted' function; don't execute shell commands"):
                    command = agent_name.title() + ("Tour" if mode == "tour" else "")
                    with self.subTest(command=command, topic=topic):
                        count = len(launches(self.log))
                        pane = self.launch(command + " " + topic)
                        self.assertEqual(pane["error"], "")
                        launched = wait_for(lambda: launches(self.log)[count:], message="agent did not start")[0]
                        env = launched["env"]
                        self.assertEqual(env["TANDEM_EDITOR"], "neovim")
                        self.assertEqual(env["TANDEM_SERVER"], self.socket)
                        self.assertEqual(env["TANDEM_WINDOW"], str(self.source))
                        self.assertEqual(Path(env["TANDEM_CLI"]), CLI)
                        self.assertEqual(env["PATH"].split(":")[0], str(CLI.parent))
                        self.assertEqual(Path(env["TANDEM_EDITOR_BIN"]).resolve(), Path(shutil.which("nvim")).resolve())
                        ask = topic or default_ask(mode)
                        if agent_name == "claude":
                            flag, system_flag, system, settings_flag, settings, separator, prompt = launched["argv"]
                            self.assertEqual((flag, system_flag, settings_flag, separator),
                                             ("--claude-flag", "--append-system-prompt", "--settings", "--"))
                            self.assertEqual(system, instructions(mode))
                            self.assertEqual(json.loads(settings), {
                                "permissions": {"allow": ["Bash(tandem *)"]},
                                "sandbox": {"network": {"allowUnixSockets": [self.socket]}}})
                            self.assertEqual(prompt, ask)
                        else:
                            self.assertEqual(launched["argv"], ["--codex-flag", "Read and follow %s. Session mode: %s. %s"
                                                                % (json.dumps(str(SKILL), ensure_ascii=False), mode, ask)])
                        self.assertEqual(self.lua("return vim.api.nvim_get_current_win()"), pane["window"])
                        self.assertEqual(self.lua("return vim.fn.mode()"), "t")
                        self.lua("vim.cmd('bwipeout! %d'); return true" % pane["buffer"])

    def test_default_agent_commands_and_missing_executable(self):
        tools = self.directory / "tools"
        tools.mkdir()
        for name in ("codex", "claude"):
            self.agent("tools/" + name)
        self.lua("vim.env.PATH=%s .. ':' .. vim.env.PATH; return true" % json.dumps(str(tools)))
        for name in ("codex", "claude"):
            with self.subTest(agent=name):
                count = len(launches(self.log))
                pane = self.launch(name.title() + " Help me code")
                argv = wait_for(lambda: launches(self.log)[count:])[0]["argv"]
                self.assertEqual(argv[0], "--no-daemon" if name == "codex" else "--append-system-prompt")
                self.lua("vim.cmd('bwipeout! %d'); vim.g.tandem_%s_cmd={'/not-installed/%s'}; return true"
                         % (pane["buffer"], name, name))
                before = self.windows()
                failed = self.launch(name.title())
                self.assertEqual(failed["error"], "Tandem: %s executable was not found: /not-installed/%s. "
                                 "Install it or set g:tandem_%s_cmd." % (name.title(), name, name))
                self.assertEqual(self.windows(), before)

    def test_rerunning_a_command_returns_to_the_running_session(self):
        agent = str(self.agent())
        self.configure(claude_cmd=[agent], codex_cmd=[agent])
        first = self.launch("Claude")
        wait_for(lambda: launches(self.log))
        windows = self.windows()
        again = self.launch("Claude")
        self.assertEqual((again["window"], again["buffer"]), (first["window"], first["buffer"]))
        self.assertEqual(self.windows(), windows)
        self.launch("Claude what does this do?")
        wait_for(lambda: "what does this do?" in "".join(
            self.lua("return vim.api.nvim_buf_get_lines(%d,0,-1,false)" % first["buffer"])),
            message="the follow-up was not typed into the agent")
        self.assertEqual(len(launches(self.log)), 1)
        other = self.launch("Codex")
        self.assertEqual(other["error"], "Tandem: Claude is already working with this window. Run :Codex! to replace it.")
        self.assertEqual(len(launches(self.log)), 1)
        replaced = self.launch("Codex!")
        self.assertNotEqual(replaced["buffer"], first["buffer"])
        self.assertFalse(self.lua("return vim.api.nvim_buf_is_valid(%d)" % first["buffer"]))
        self.assertEqual(len(wait_for(lambda: len(launches(self.log)) == 2 and launches(self.log))), 2)
        self.assertEqual(len(self.windows()), len(windows))

    def test_an_agent_whose_code_window_closed_gets_a_new_one(self):
        self.configure(claude_cmd=[str(self.agent())])
        pane = self.launch("Claude")
        wait_for(lambda: launches(self.log))
        self.call("highlight", "--start", "2", "--note", "before")
        self.lua("vim.api.nvim_win_close(%d, true); return true" % self.source)
        wait_for(lambda: self.marks() == [], message="annotations stayed after the window closed")
        self.assertIn("run :Claude", self.call("state", success=False)["error"])

        # From the agent's pane, the agent gets a new code window beside it.
        again = self.launch("Claude", window=pane["window"])
        self.assertEqual((again["window"], again["error"]), (pane["window"], ""))
        state = self.call("state")["result"]
        self.assertNotIn(state["target"], (self.source, pane["window"]))
        self.assertEqual(state["focus"], "agent")

        # From a code window in another tab, the agent comes to that window.
        self.lua("vim.api.nvim_win_close(%d, true); return true" % state["target"])
        window = self.lua("vim.cmd('tabnew'); return vim.api.nvim_get_current_win()")
        moved = self.launch("Claude", window=window)
        self.assertEqual((moved["buffer"], moved["error"]), (pane["buffer"], ""))
        self.assertEqual(self.call("state")["result"]["target"], window)
        self.assertEqual(len(launches(self.log)), 1)

    def test_a_tour_command_switches_a_running_session_to_tour_mode(self):
        self.configure(claude_cmd=[str(self.agent())])
        pane = self.launch("Claude")
        wait_for(lambda: launches(self.log))
        self.launch("ClaudeTour the parser")
        wait_for(lambda: "Switch to tour mode. the parser" in "".join(
            self.lua("return vim.api.nvim_buf_get_lines(%d,0,-1,false)" % pane["buffer"])),
            message="the mode switch was not typed into the agent")

    def test_launching_from_a_scratch_buffer_keeps_it_and_ignores_its_lines(self):
        self.configure(claude_cmd=[str(self.agent())])
        scratch = self.lua("""
            vim.cmd('tabnew')
            vim.bo.buftype = 'nofile'
            vim.bo.bufhidden = 'wipe'
            vim.api.nvim_buf_set_lines(0, 0, -1, false, {'a', 'b', 'c', 'd'})
            return {window = vim.api.nvim_get_current_win(), buffer = vim.api.nvim_get_current_buf()}
        """)
        self.launch("2,3Claude what do these lines mean", window=scratch["window"])
        self.assertEqual(wait_for(lambda: launches(self.log))[0]["argv"][-1], "what do these lines mean")
        self.assertEqual(self.lua("return vim.api.nvim_buf_get_lines(%d,0,-1,false)" % scratch["buffer"]),
                         ["a", "b", "c", "d"])

    def test_relaunching_before_a_wiped_agent_reports_its_exit(self):
        self.configure(claude_cmd=[str(self.agent())])
        first = self.launch("Claude")
        wait_for(lambda: launches(self.log))
        # One command, so the old agent's exit callback cannot run in between.
        second = self.launch("bwipeout! %d | Claude" % first["buffer"])
        self.assertEqual(second["error"], "")
        wait_for(lambda: len(launches(self.log)) == 2)
        self.assertEqual(self.launch("Claude")["buffer"], second["buffer"])
        self.assertEqual(len(launches(self.log)), 2)

    def test_a_hidden_agent_pane_comes_back(self):
        self.configure(claude_cmd=[str(self.agent())])
        first = self.launch("Claude")
        wait_for(lambda: launches(self.log))
        self.lua("vim.o.hidden = false; vim.api.nvim_win_call(%d, function() vim.cmd('quit') end); return true"
                 % first["window"])
        self.assertTrue(self.lua("return vim.fn.jobwait({vim.bo[%d].channel}, 0)[1] == -1" % first["buffer"]))
        again = self.launch("Claude")
        self.assertEqual(again["buffer"], first["buffer"])
        self.assertEqual(len(launches(self.log)), 1)

    def test_selected_lines_are_included_in_the_prompt(self):
        self.configure(claude_cmd=[str(self.agent())])
        name = self.lua("return vim.fn.fnamemodify(vim.fn.bufname(%d), ':~:.')" % self.buffer)
        pane = self.launch("2,4Claude explain this")
        self.assertEqual(wait_for(lambda: launches(self.log))[0]["argv"][-1],
                         "Look at lines 2-4 of %s. explain this" % name)
        self.lua("vim.cmd('bwipeout! %d'); return true" % pane["buffer"])
        self.launch("3Claude")
        self.assertEqual(wait_for(lambda: launches(self.log)[1:])[0]["argv"][-1], "Look at line 3 of %s." % name)

    def test_agent_exit_clears_annotations_and_closes_a_cleanly_finished_pane(self):
        self.configure(claude_cmd=[str(self.agent(lifetime=2))])
        pane = self.launch("Claude")
        self.call("highlight", "--start", "2", "--note", "from the agent")
        self.assertEqual(len(self.marks()), 1)
        wait_for(lambda: not self.lua("return vim.api.nvim_buf_is_valid(%d)" % pane["buffer"]), timeout=8,
                 message="the agent pane stayed open after a clean exit")
        self.assertEqual(self.marks(), [])
        self.assertEqual(len(self.windows()), 2)

        self.configure(claude_cmd=[str(self.agent("failing agent", lifetime=0, exit_code=3))])
        self.lua("vim.api.nvim_create_autocmd('TermClose', {callback=function() vim.g.exit_status=vim.v.event.status end}); return true")
        failed = self.launch("Claude")
        wait_for(lambda: self.lua("return vim.g.exit_status") == 3, message="the failing agent did not exit")
        time.sleep(0.3)
        self.assertTrue(self.lua("return vim.api.nvim_win_is_valid(%d)" % failed["window"]))

    def test_launching_from_a_terminal_or_start_screen_finds_a_code_window(self):
        self.configure(claude_cmd=[str(self.agent())])
        pane = self.launch("Claude", window=self.terminal)
        self.assertEqual(wait_for(lambda: launches(self.log))[0]["env"]["TANDEM_WINDOW"], str(self.source))
        self.lua("vim.cmd('bwipeout! %d'); return true" % pane["buffer"])

        start = self.lua("vim.cmd('tabnew'); vim.bo.buftype = 'nofile'; return vim.api.nvim_get_current_win()")
        self.launch("Claude", window=start)
        target = int(wait_for(lambda: launches(self.log)[1:])[0]["env"]["TANDEM_WINDOW"])
        self.assertEqual(target, start)
        self.assertEqual(self.lua("return vim.bo[vim.api.nvim_win_get_buf(%d)].buftype" % target), "")

    def test_configuration_accepts_strings_and_column_widths(self):
        agent = fake_agent(self.directory / "agent", self.log)
        self.lua("vim.g.tandem_claude_cmd = %s; vim.g.tandem_width = 30; return true"
                 % json.dumps(str(agent) + " --from-string"))
        pane = self.launch("Claude")
        self.assertEqual(wait_for(lambda: launches(self.log))[0]["argv"][0], "--from-string")
        self.assertEqual(self.lua("return vim.api.nvim_win_get_width(%d)" % pane["window"]), 30)
        self.lua("vim.cmd('bwipeout! %d'); vim.g.tandem_width = 'wide'; return true" % pane["buffer"])
        self.assertIn("g:tandem_width must be", self.launch("Claude")["error"])
        warnings = self.lua("""
            local seen = {}
            vim.notify = function(message) table.insert(seen, message) end
            require('tandem').setup({widht = 0.5})
            return seen
        """)
        self.assertEqual(warnings, ['tandem: unknown option "widht"'])

    def test_help_documents_every_command_and_option(self):
        docs = self.directory / "help"
        shutil.copytree(ROOT / "doc", docs)
        # Duplicate or malformed tags make :helptags fail.
        self.lua("vim.cmd.helptags(vim.fn.fnameescape(%s)); return true" % json.dumps(str(docs)))
        tags = {line.split("\t")[0] for line in (docs / "tags").read_text().splitlines()}
        commands = re.findall(r"^command!(?:\s+-\S+)*\s+(\w+)", (ROOT / "plugin/tandem.vim").read_text(), re.M)
        options = re.findall(r"`(g:tandem_\w+)`", (ROOT / "README.md").read_text())
        self.assertEqual(len(commands), 5)
        self.assertEqual(len(set(options)), 3)
        for tag in ["tandem", "tandem-permissions"] + [":" + name for name in commands] + options:
            self.assertIn(tag, tags)

    def test_health_check_reports_the_setup(self):
        for codex in (None, [], ""):
            with self.subTest(codex_cmd=codex):
                value = "nil" if codex is None else "vim.json.decode(%s)" % json.dumps(json.dumps(codex))
                self.lua("vim.g.tandem_codex_cmd = %s; return true" % value)
                self.lua("vim.cmd('checkhealth tandem'); return true")
                # Newer Neovims check health asynchronously and set the filetype once done.
                lines = wait_for(lambda: self.lua(
                    "return vim.bo.filetype == 'checkhealth' and vim.api.nvim_buf_get_lines(0, 0, -1, false) or vim.NIL"))
                text = "\n".join(lines)
                self.assertIn("Neovim", text)
                self.assertNotIn("Failed to run healthcheck", text)
                self.assertEqual(codex is None, "g:tandem_codex_cmd must be" not in text, text)


if __name__ == "__main__":
    unittest.main()
