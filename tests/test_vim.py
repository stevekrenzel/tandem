"""Drive the tandem helper and launch commands against real terminal Vim and MacVim.

Terminal Vim needs +socketserver (VIM_TEST_BINARY=/path/to/vim). MacVim GUI
tests open windows, so they are opt-in: MACVIM_GUI_TESTS=1.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid

from support import CLI, SKILL, VIM_STARTUP, clean_env, default_ask, fake_agent, git, instructions, launches, make_repo, wait_for

MACVIM = os.environ.get("MACVIM_BINARY", "/Applications/MacVim.app/Contents/MacOS/Vim")
TERMINAL_VIM = os.environ.get("VIM_TEST_BINARY") or shutil.which("vim")
TERMINAL_FEATURES = (subprocess.run([TERMINAL_VIM, "--version"], text=True, capture_output=True).stdout
                     if TERMINAL_VIM else "")


def vim_string(value):
    return "'" + value.replace("'", "''") + "'"


class VimCases:
    binary = None
    use_gui = False

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vt-", dir="/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name).resolve()
        self.file, self.other = make_repo(self.directory)
        self.server = ("TANDEM_TEST_" + uuid.uuid4().hex[:12].upper() if self.use_gui
                       else str(self.directory / "vim.sock"))
        # An outer Neovim must not capture requests meant for Vim.
        self.env = clean_env(NVIM="/nonexistent/outer-neovim.sock", TANDEM_EDITOR="vim",
                             TANDEM_SERVER=self.server, TANDEM_EDITOR_BIN=self.binary)
        if not self.use_gui:
            self.env["VIM_CLIENTSERVER"] = "socket"
        mode = ["-g", "-f"] if self.use_gui else ["-e", "-s", "--clientserver", "socket"]
        hold = [] if self.use_gui else ["-c", "while 1 | sleep 10m | endwhile"]
        self.proc = subprocess.Popen([self.binary, *mode, "-N", "-u", "NONE", "-U", "NONE", "-i", "NONE", "-n",
                                      "--servername", self.server, "--cmd", VIM_STARTUP, *hold],
                                     cwd=self.directory, env=self.env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop)
        wait_for(self.ready, timeout=10, message="Vim did not start its server")
        self.source = self.expr("win_getid()")
        self.commands("execute 'edit ' . fnameescape(" + vim_string(str(self.file)) + ")")
        self.buffer = self.expr("bufnr()")
        self.commands("vertical new", "call term_start(['sh','-c','cat'],{'curwin':1})")
        self.terminal = self.expr("win_getid()")
        self.env["TANDEM_WINDOW"] = str(self.source)
        self.log = self.directory / "launches.jsonl"

    def ready(self):
        if self.proc.poll() is not None:
            raise AssertionError("Vim exited during startup")
        result = subprocess.run([self.binary, "--servername", self.server, "--remote-expr", "v:servername"],
                                env=self.env, capture_output=True, text=True, timeout=2)
        return result.returncode == 0 and result.stdout.strip() != ""

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
                self.proc.kill()
                self.proc.wait(timeout=3)

    def expr(self, expression):
        result = subprocess.run([self.binary, "--servername", self.server, "--remote-expr",
                                 "json_encode(" + expression + ")"],
                                env=self.env, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def commands(self, *commands):
        return self.expr("execute(json_decode(%s))" % vim_string(json.dumps(commands, ensure_ascii=False)))

    def call(self, *args, success=True):
        result = subprocess.run([str(CLI), *args], env=self.env, cwd=self.directory,
                                text=True, capture_output=True, timeout=12)
        self.assertEqual(result.returncode == 0, success, result.stderr or result.stdout)
        return json.loads(result.stdout)

    def properties(self, buffer=None):
        return self.expr("prop_list(1,{'bufnr':%d,'end_lnum':-1})" % (buffer or self.buffer))

    def notes(self, buffer=None):
        return [prop["text"].strip() for prop in self.properties(buffer) if "text" in prop]

    def baseline(self, window):
        return self.expr("getbufline(winbufnr(%d),1,'$')" % window)

    def agent(self, name="fake agent", **behavior):
        return fake_agent(self.directory / name, self.log, **behavior)

    def launch(self, command, window=None):
        """Runs a launch command as the user would and reports where it left the user."""
        self.commands("call win_gotoid(%d)" % (window or self.source), "let v:errmsg = ''", command)
        return {"window": self.expr("win_getid()"), "buffer": self.expr("bufnr()"), "error": self.expr("v:errmsg")}

    def screen_text(self, buffer):
        return self.expr("join(map(range(1, term_getsize(%d)[0]), 'term_getline(%d, v:val)'))" % (buffer, buffer))

    # ---------------------------------------------------- state, read, show

    def test_state_and_read_include_unsaved_changes(self):
        self.commands("call setbufline(%d,1,'not on disk')" % self.buffer, "call cursor(1, 1)",
                      "call win_execute(%d, 'call cursor(3, 5)')" % self.source)
        state = self.call("state")["result"]
        self.assertEqual(state["target"], self.source)
        self.assertEqual(state["current_window"], self.terminal)
        self.assertEqual(state["focus"], "other")
        self.assertEqual(state["cursor"], [3, 5])
        self.assertTrue(state["context"]["modified"])
        self.assertEqual(self.call("read", "--start", "1", "--end", "2")["result"]["lines"],
                         ["not on disk", "line 2"])
        self.assertEqual(self.call("read", "other.py")["result"]["lines"], ["other file", "second line"])

    def test_state_works_while_the_user_is_in_another_tab(self):
        self.commands("call win_execute(%d, 'lcd /usr')" % self.source, "tabnew")
        self.assertEqual(self.call("state")["result"]["cwd"], "/usr")

    def test_unreachable_editor_explains_sandbox_and_restart(self):
        # Vim's client exits 0 when it cannot connect.
        self.env["TANDEM_SERVER"] = (str(self.directory / "missing.sock") if not self.use_gui
                                     else "TANDEM_MISSING_" + uuid.uuid4().hex[:8].upper())
        result = subprocess.run([str(CLI), "state"], env=self.env, cwd=self.directory,
                                text=True, capture_output=True, timeout=12)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("If this shell is sandboxed", result.stderr)

    def test_files_that_are_not_utf8_read_as_latin1(self):
        (self.directory / "latin1.txt").write_bytes(b"caf\xe9\n")
        self.assertEqual(self.call("read", "latin1.txt")["result"]["lines"], ["caf\u00e9"])

    def test_a_file_with_a_swap_file_opens_read_only(self):
        swaps = self.directory / "swap"
        swaps.mkdir()
        # A crashed session leaves its swap file behind, with a change the user never saved.
        crashed = subprocess.Popen(
            [self.binary, "-e", "-s", "-N", "-u", "NONE", "-i", "NONE", "--cmd", "set directory=%s//" % swaps,
             "other.py", "-c", "call setline(1, 'unsaved') | preserve", "-c", "while 1 | sleep 10m | endwhile"],
            cwd=self.directory, env=clean_env(), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_for(lambda: any(swaps.iterdir()), message="the other editor made no swap file")
        crashed.kill()
        crashed.wait()
        self.commands("let &directory = %s" % vim_string(str(swaps) + "//"), "set updatecount=200")
        self.call("show", "other.py")
        buffer = self.expr("winbufnr(%d)" % self.source)
        self.assertEqual(self.expr("getbufline(%d,1,'$')" % buffer), ["other file", "second line"])
        self.assertTrue(self.expr("getbufvar(%d,'&readonly')" % buffer))

    def test_commands_reload_files_changed_on_disk_but_keep_unsaved_buffers(self):
        self.file.write_text("agent edit\n" + self.file.read_text())
        later = time.time() + 5
        os.utime(self.file, (later, later))
        self.call("show", str(self.file), "--start", "1", "--end", "2")
        self.assertEqual(self.expr("getbufline(%d,1,2)" % self.buffer), ["agent edit", "line 1"])
        self.assertFalse(self.expr("getbufvar(%d,'&modified')" % self.buffer))

        self.commands("call setbufline(%d,1,'user edit')" % self.buffer)
        self.file.write_text("second agent edit\n")
        os.utime(self.file, (later + 5, later + 5))
        self.assertEqual(self.call("read", "--end", "1")["result"]["lines"], ["user edit"])
        self.assertTrue(self.expr("getbufvar(%d,'&modified')" % self.buffer))

    def test_quoted_multiline_notes_are_literal(self):
        note = "O'Brien\nü \\ $HOME `touch sentinel` $(touch sentinel) ');throw 'injected"
        self.call("highlight", "--start", "2", "--note", note)
        self.assertEqual(self.notes(), note.split("\n"))
        self.assertFalse((self.directory / "sentinel").exists())
        self.assertFalse(self.expr("getbufvar(%d,'&modified')" % self.buffer))

    def test_show_preserves_focus_buffers_options_and_autosave(self):
        self.commands("set nohidden autowrite autowriteall", "let g:leave_count=0",
                      "autocmd BufLeave,FocusLost * let g:leave_count+=1 | silent! wall",
                      "call setbufvar(%d,'&bufhidden','wipe')" % self.buffer,
                      "call setbufline(%d,1,'unsaved change')" % self.buffer)
        self.call("show", str(self.other), "--start", "2", "--note", "A tour note")
        self.assertEqual(self.expr("win_getid()"), self.terminal)
        self.assertEqual(self.expr("getcurpos(%d)[1:2]" % self.source), [2, 1])
        self.assertEqual(self.expr("g:leave_count"), 0)
        self.assertEqual(self.expr("getbufline(%d,1,1)" % self.buffer), ["unsaved change"])
        self.assertEqual(self.expr("getbufvar(%d,'&bufhidden')" % self.buffer), "wipe")
        self.assertEqual(self.expr("[&hidden,&autowrite,&autowriteall]"), [0, 1, 1])
        self.assertTrue(self.file.read_text().startswith("line 1\n"))

    def test_show_without_a_range_opens_the_file_without_highlighting(self):
        result = self.call("show", "other.py")["result"]
        self.assertEqual(list(result), ["file"])
        self.assertEqual(self.properties(self.expr("winbufnr(%d)" % self.source)), [])

    def test_annotations_and_clear_preserve_text_and_other_properties(self):
        self.commands("call prop_type_add('OtherPlugin',{'highlight':'Error'})",
                      "call prop_add(1,1,{'type':'OtherPlugin','bufnr':%d,'length':1})" % self.buffer)
        self.call("show", str(self.file), "--start", "10", "--end", "15", "--note", "Tour note")
        self.assertEqual(self.notes(), ["Tour note"])
        self.assertTrue(any(p["lnum"] == 15 and p["type"].startswith("TandemRange") for p in self.properties()))
        self.assertFalse(self.expr("getbufvar(%d,'&modified')" % self.buffer))
        self.call("clear")
        self.assertEqual([p["type"] for p in self.properties()], ["OtherPlugin"])

    def test_invalid_requests_leave_the_view_and_eventignore_in_place(self):
        result = self.call("diff", str(self.file))["result"]
        self.commands("let &eventignore='TextChanged,InsertLeave'")
        self.call("show", str(self.directory / "missing.py"), success=False)
        self.call("show", str(self.other), "--start", "999", success=False)
        self.call("highlight", "2", success=False)
        self.call("--window", "999999", "state", success=False)
        self.assertEqual(self.expr("&eventignore"), "TextChanged,InsertLeave")
        self.assertEqual(self.expr("win_getid()"), self.terminal)
        self.assertNotEqual(self.expr("win_id2tabwin(%d)" % result["baseline_window"]), [0, 0])
        self.assertTrue(self.expr("getwinvar(%d,'&diff')" % self.source))

    def test_windows_have_independent_annotations_and_tandem_clear_removes_all(self):
        self.commands("call prop_type_add('OtherPlugin',{'highlight':'Error'})",
                      "call prop_add(1,1,{'type':'OtherPlugin','bufnr':%d,'length':1})" % self.buffer,
                      "call win_execute(%d,'leftabove vsplit | let g:second_source=win_getid()')" % self.source)
        second = self.expr("g:second_source")
        self.call("highlight", "--start", "3", "--note", "first tour")
        self.call("--window", str(second), "highlight", "--start", "5", "--note", "second tour")
        self.call("clear")
        self.assertEqual(self.notes(), ["second tour"])
        self.commands("TandemClear")
        self.assertEqual([p["type"] for p in self.properties()], ["OtherPlugin"])
        self.assertEqual(self.expr("win_getid()"), self.terminal)

    def test_closing_the_code_window_beside_its_comparison_cleans_up(self):
        self.call("diff")
        self.commands("call win_execute(%d, 'hide')" % self.terminal,
                      "let v:errmsg = ''", "call win_execute(%d, 'close')" % self.source)
        wait_for(lambda: self.expr("len(filter(getbufinfo(), 'v:val.name =~# \"^tandem://\"'))") == 0,
                 message="the comparison stayed open")
        self.assertEqual(self.expr("v:errmsg"), "")
        self.assertEqual(self.expr("prop_type_get('TandemNote_%d')" % self.source), {})

    def test_closing_a_code_window_clears_its_annotations(self):
        self.commands("set hidden")
        self.call("highlight", "--start", "3", "--note", "temporary")
        self.commands("call win_execute(%d, 'close')" % self.source)
        wait_for(lambda: self.properties() == [], message="annotations stayed after the window closed")
        wait_for(lambda: self.expr("prop_type_get('TandemNote_%d')" % self.source) == {},
                 message="the window's property types were not deleted")
        self.assertIn("closed", self.call("state", success=False)["error"])

    # ----------------------------------------------------------------- diff

    def test_diff_compares_unsaved_content_and_cleans_up(self):
        self.commands("call setbufline(%d,1,'unsaved change')" % self.buffer)
        result = self.call("diff", str(self.file))["result"]
        self.assertEqual(self.baseline(result["baseline_window"]), ["line %d" % i for i in range(1, 61)])
        self.assertEqual(self.call("read", "--end", "1")["result"]["lines"], ["unsaved change"])
        self.assertEqual(self.expr("win_getid()"), self.terminal)
        self.assertEqual(self.expr("len(getwininfo())"), 3)
        self.call("clear")
        self.assertEqual(self.expr("len(getwininfo())"), 2)
        self.assertFalse(self.expr("getwinvar(%d,'&diff')" % self.source))
        self.assertTrue(self.expr("getbufvar(%d,'&modified')" % self.buffer))

    def test_git_comparison_does_not_use_the_configured_shell(self):
        self.commands("set shell=/usr/bin/false shellcmdflag=-ic")
        self.assertTrue(self.call("diff")["ok"])
        self.assertEqual(self.expr("[&shell, &shellcmdflag]"), ["/usr/bin/false", "-ic"])

    def test_git_warnings_stay_out_of_the_baseline(self):
        self.commands("let $GIT_TRACE = '1'")
        result = self.call("diff")["result"]
        self.assertEqual(self.baseline(result["baseline_window"]), ["line %d" % i for i in range(1, 61)])

    def test_diff_handles_crlf_and_deleted_directories(self):
        folder = self.directory / "removed"
        folder.mkdir()
        file = folder / "old.py"
        file.write_bytes(b"first\r\nsecond\r\n")
        git(self.directory, "add", ".")
        git(self.directory, "commit", "-qm", "CRLF baseline")
        file.unlink()
        folder.rmdir()
        result = self.call("diff", str(file))["result"]
        self.assertEqual(self.baseline(result["baseline_window"]), ["first", "second"])
        self.assertEqual(self.call("read")["result"]["lines"], [""])
        self.call("clear")
        self.assertFalse(file.exists())

    def test_closing_the_comparison_pane_ends_the_comparison(self):
        baseline = self.call("diff")["result"]["baseline_window"]
        self.commands("call win_execute(%d, 'close')" % baseline)
        wait_for(lambda: not self.expr("getwinvar(%d,'&diff')" % self.source),
                 message="the code window stayed in diff mode")
        self.assertTrue(self.call("diff")["ok"])

    def test_diff_does_not_join_an_unrelated_comparison(self):
        self.commands("call win_execute(%d,'leftabove vsplit | diffthis')" % self.source)
        self.assertIn("diff open", self.call("diff", str(self.file), success=False)["error"])
        self.assertEqual(self.expr("len(getwininfo())"), 3)
        self.assertFalse(self.expr("getwinvar(%d,'&diff')" % self.source))

    def test_diff_checks_the_code_windows_tab_when_the_user_is_elsewhere(self):
        self.commands("call win_execute(%d,'leftabove vsplit | diffthis')" % self.source,
                      "tabnew", "call term_start(['sh','-c','cat'],{'curwin':1})")
        current = self.expr("win_getid()")
        windows = self.expr("len(getwininfo())")
        self.call("diff", str(self.file), success=False)
        self.assertEqual(self.expr("len(getwininfo())"), windows)
        self.assertEqual(self.expr("win_getid()"), current)

    def test_default_diff_resolves_a_relatively_opened_buffer(self):
        self.commands("call win_execute(%d,'edit other.py')" % self.source)
        result = self.call("diff")["result"]
        self.assertEqual(Path(result["file"]).resolve(), self.other.resolve())
        self.assertEqual(self.baseline(result["baseline_window"]), ["other file", "second line"])

    # --------------------------------------------------------------- launch

    def test_launchers_pass_the_connection_instructions_and_literal_prompt(self):
        agent = self.agent()
        if not self.use_gui:
            # The pane must learn the transport from Vim's own arguments.
            self.commands("unlet $VIM_CLIENTSERVER")
        for name in ("codex", "claude"):
            self.commands("let g:tandem_%s_cmd=[%s,'--custom-flag']" % (name, vim_string(str(agent))))
            for mode in ("partner", "tour"):
                for topic in ("", "Explain the 'quoted' function; do not run shell commands"):
                    command = name.title() + ("Tour" if mode == "tour" else "")
                    with self.subTest(command=command, topic=topic):
                        count = len(launches(self.log))
                        pane = self.launch(command + " " + topic)
                        self.assertEqual(pane["error"], "")
                        launched = wait_for(lambda: launches(self.log)[count:], message="agent did not start")[0]
                        env = launched["env"]
                        if not self.use_gui:
                            self.assertEqual(env.get("VIM_CLIENTSERVER"), "socket")
                        self.assertEqual(env["TANDEM_EDITOR"], "vim")
                        self.assertEqual(env["TANDEM_SERVER"], self.server)
                        self.assertEqual(env["TANDEM_WINDOW"], str(self.source))
                        self.assertEqual(Path(env["TANDEM_EDITOR_BIN"]).resolve(), Path(self.binary).resolve())
                        self.assertEqual(Path(env["TANDEM_CLI"]), CLI)
                        self.assertEqual(env["PATH"].split(":")[0], str(CLI.parent))
                        ask = topic or default_ask(mode)
                        if name == "claude":
                            flag, system_flag, system, settings_flag, settings, separator, prompt = launched["argv"]
                            self.assertEqual((flag, system_flag, settings_flag, separator),
                                             ("--custom-flag", "--append-system-prompt", "--settings", "--"))
                            self.assertEqual(system, instructions(mode))
                            self.assertEqual(json.loads(settings)["permissions"], {"allow": ["Bash(tandem *)"]})
                            self.assertEqual(prompt, ask)
                        else:
                            self.assertEqual(launched["argv"], ["--custom-flag", "Read and follow %s. Session mode: %s. %s"
                                                                % (json.dumps(str(SKILL), ensure_ascii=False), mode, ask)])
                        self.assertEqual(self.expr("win_getid()"), pane["window"])
                        self.commands("bwipeout! %d" % pane["buffer"])

    def test_missing_executable_is_reported_without_opening_a_pane(self):
        self.commands("let g:tandem_codex_cmd = ['/not-installed/codex']")
        windows = self.expr("len(getwininfo())")
        failed = self.launch("Codex")
        self.assertEqual(failed["error"], "Tandem: Codex executable was not found: /not-installed/codex. "
                         "Install it or set g:tandem_codex_cmd.")
        self.assertEqual(self.expr("len(getwininfo())"), windows)

    def test_rerunning_a_command_returns_to_the_running_session(self):
        agent = vim_string(str(self.agent()))
        self.commands("let g:tandem_claude_cmd = [%s]" % agent, "let g:tandem_codex_cmd = [%s]" % agent)
        first = self.launch("Claude")
        wait_for(lambda: launches(self.log))
        windows = self.expr("len(getwininfo())")
        again = self.launch("Claude what does this do?")
        self.assertEqual((again["window"], again["buffer"]), (first["window"], first["buffer"]))
        self.assertEqual(self.expr("len(getwininfo())"), windows)
        wait_for(lambda: "what does this do?" in self.screen_text(first["buffer"]),
                 message="the follow-up was not typed into the agent")
        self.assertEqual(len(launches(self.log)), 1)
        self.assertIn("Run :Codex! to replace it", self.launch("Codex")["error"])
        replaced = self.launch("Codex!")
        self.assertNotEqual(replaced["buffer"], first["buffer"])
        self.assertFalse(self.expr("bufexists(%d)" % first["buffer"]))
        wait_for(lambda: len(launches(self.log)) == 2)
        self.assertEqual(self.expr("len(getwininfo())"), windows)

    def test_quit_hides_the_agent_and_rerunning_brings_it_back(self):
        self.commands("let g:tandem_claude_cmd = [%s]" % vim_string(str(self.agent())))
        first = self.launch("Claude")
        wait_for(lambda: launches(self.log))
        self.commands("call win_execute(%d, 'quit')" % first["window"])
        self.assertEqual(self.expr("win_id2tabwin(%d)" % first["window"]), [0, 0])
        self.assertIn("running", self.expr("term_getstatus(%d)" % first["buffer"]))
        self.assertEqual(self.launch("Claude")["buffer"], first["buffer"])
        self.assertEqual(len(launches(self.log)), 1)

    def test_an_agent_whose_code_window_closed_gets_a_new_one(self):
        self.commands("let g:tandem_claude_cmd = [%s]" % vim_string(str(self.agent())))
        pane = self.launch("Claude")
        wait_for(lambda: launches(self.log))
        self.call("highlight", "--start", "2", "--note", "before")
        self.commands("call win_execute(%d, 'close')" % self.source)
        wait_for(lambda: self.properties() == [], message="annotations stayed after the window closed")
        self.assertIn("run :Claude", self.call("state", success=False)["error"])
        again = self.launch("Claude", window=pane["window"])
        self.assertEqual((again["window"], again["error"]), (pane["window"], ""))
        target = self.call("state")["result"]["target"]
        self.assertNotIn(target, (self.source, pane["window"]))
        self.call("show", str(self.file), "--start", "2", "--note", "after")
        self.assertEqual(self.expr("winbufnr(%d)" % target), self.buffer)
        self.assertEqual(self.notes(), ["after"])
        self.assertEqual(len(launches(self.log)), 1)

    def test_selected_lines_are_included_in_the_prompt(self):
        self.commands("let g:tandem_claude_cmd = [%s]" % vim_string(str(self.agent())))
        name = self.expr("fnamemodify(bufname(%d), ':~:.')" % self.buffer)
        self.launch("2,4Claude explain this")
        self.assertEqual(wait_for(lambda: launches(self.log))[0]["argv"][-1],
                         "Look at lines 2-4 of %s. explain this" % name)

    def test_agent_exit_clears_annotations_and_closes_a_cleanly_finished_pane(self):
        self.commands("let g:tandem_claude_cmd = [%s]" % vim_string(str(self.agent(lifetime=2))))
        pane = self.launch("Claude")
        self.call("highlight", "--start", "2", "--note", "from the agent")
        self.assertEqual(self.notes(), ["from the agent"])
        wait_for(lambda: not self.expr("bufexists(%d)" % pane["buffer"]), timeout=8,
                 message="the agent pane stayed open after a clean exit")
        self.assertEqual(self.properties(), [])
        self.assertEqual(self.expr("len(getwininfo())"), 2)

        self.commands("let g:tandem_claude_cmd = [%s]"
                      % vim_string(str(self.agent("failing agent", lifetime=0, exit_code=3))))
        failed = self.launch("Claude")
        wait_for(lambda: self.expr("term_getstatus(%d)" % failed["buffer"]).startswith("finished"),
                 message="the failing agent did not exit")
        time.sleep(0.3)
        self.assertNotEqual(self.expr("win_id2tabwin(%d)" % failed["window"]), [0, 0])


@unittest.skipUnless("+socketserver" in TERMINAL_FEATURES, "Set VIM_TEST_BINARY to terminal Vim with +socketserver")
class TerminalVimTest(VimCases, unittest.TestCase):
    binary = TERMINAL_VIM


@unittest.skipUnless(os.environ.get("MACVIM_GUI_TESTS") == "1" and Path(MACVIM).is_file(),
                     "MacVim GUI tests are opt-in: MACVIM_GUI_TESTS=1")
class MacVimTest(VimCases, unittest.TestCase):
    binary = MACVIM
    use_gui = True


if __name__ == "__main__":
    unittest.main()
