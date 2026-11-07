# Neovim Tour

Run Codex in a Neovim or MacVim terminal split and let it walk you through the code beside it.
Codex can open files, point out a range, add temporary notes, and compare the live
buffer with a Git revision while you keep chatting in the terminal.

The connection uses the editor's built-in remote client: Neovim's RPC socket or
MacVim's native named server. A
global Codex skill teaches the walkthrough workflow; the bundled helper handles
the editor operations. There is no extra server to run or Python package to install.

## Install

Requirements: Python 3.9+, a current Codex CLI with `--no-daemon` support on your
PATH, and either Neovim 0.11+ (macOS/Linux) or MacVim with Vim 9.1+ (macOS).
MacVim needs `+clientserver`, `+terminal`, and `+textprop`; current releases include
them. Git is needed for comparisons. Authenticate with Codex normally before
launching a tour.

From this checkout:

```sh
python3 install.py
```

For MacVim, or both editors:

```sh
python3 install.py --editor macvim
python3 install.py --editor both
```

The installer links the selected editor package and the shared skill and helper:

| Component | Default location |
| --- | --- |
| Neovim plugin | `~/.local/share/nvim/site/pack/neovim-tour/start/neovim-tour` |
| MacVim plugin | `~/.vim/pack/neovim-tour/start/neovim-tour` |
| Codex skill | `~/.agents/skills/neovim-tour` |
| Optional shell command | `~/.local/bin/nvim-tour` |

It does not edit `init.vim`, `init.lua`, `.vimrc`, `.gvimrc`, or Codex settings. Existing destinations
are checked before installation and are never overwritten. Running it again is
safe. The plugin path honors `XDG_DATA_HOME` and `NVIM_APPNAME`; use
`--nvim-data-dir`, `--vim-dir`, `--skill-dir`, and `--bin-dir` for custom locations.

Keep this checkout where you installed it, since the links point here. To share
it, send or publish the repository; each person runs the installer in their own
checkout. No machine-specific paths or credentials are stored in the source.

## Take a tour

Open your project in Neovim or the MacVim GUI, then run this from a code window:

```vim
:Codex Walk me through how authentication works
```

Or run `:Codex` and choose the topic in chat. The command opens a terminal on the
right, passes the connection and original code window to Codex, and invokes the skill.
The default launch bypasses Codex's shared daemon so the child session inherits
this editor's connection details.

Useful prompts:

- "Walk me through this branch's changes against main, one stop at a time."
- "Explain this function and follow the most important call sites."
- "Show me where this PR changes error handling, and compare before and after."

Say "next" to advance or ask a question at any stop. Highlighting and notes do
not change source text. Tour navigation preserves modified buffers, suppresses
navigation-triggered autosave hooks, and leaves the Codex terminal focused.
File loading and syntax events still run normally, including your own plugins.

`:TourClear` removes all tour annotations and temporary comparison panes. Close
the terminal split normally when finished. To switch code targets, start `:Codex`
from the desired code window. Each target has independent annotations.

The PR's code must be available in your checkout for accurate navigation. This
tool does not automatically check out branches or fetch PRs.

## Helper commands

The launcher supplies `NEOVIM_TOUR_CLI`, so the skill can use an absolute helper
path even if `~/.local/bin` is not on PATH:

```sh
"$NEOVIM_TOUR_CLI" state
"$NEOVIM_TOUR_CLI" read --start 20 --end 80
"$NEOVIM_TOUR_CLI" show src/server.py --line 24 --end 38 --note "Request entry"
"$NEOVIM_TOUR_CLI" highlight 45 --end 53 --note "Retry handling"
"$NEOVIM_TOUR_CLI" diff src/server.py --base HEAD
"$NEOVIM_TOUR_CLI" clear
```

All commands return JSON and use a nonzero exit status for errors. Paths are
resolved in the caller's working directory. Line numbers are one-based and
inclusive. `read` includes unsaved changes; it defaults to 80 lines. `diff` omits
the file argument to use the current code buffer, and defaults to `HEAD`. An
added file has an empty baseline. Deleted files can be compared even when their
parent directory is gone. The baseline buffer is temporary and read-only.

For a branch comparison, use its merge-base with the intended base branch:

```sh
base=$(git merge-base HEAD main)
"$NEOVIM_TOUR_CLI" diff src/server.py --base "$base"
```

To connect from an external shell, use explicit connection flags:

```sh
nvim-tour --server /path/to/nvim/socket --window 1000 state
nvim-tour --editor macvim --server VIM --window 1000 state
```

Inside the editor, `:echo v:servername` shows the connection address (a socket for
Neovim, a named server for MacVim), and `:echo win_getid()` shows
the current window ID. MacVim uses its own executable for remote calls, which
avoids accidentally using Apple's system `vim`. The helper fails if the target closes or becomes a special
buffer. It does not guess a different window or editor.

## Configure

Neovim: optional Lua configuration (in `init.lua`, or a `lua` block in `init.vim`):

```lua
require("neovim_tour").setup({
  codex_cmd = { "codex", "--no-daemon" },
  width = 0.42, -- Fraction of the two-pane width used by the terminal.
})
```

MacVim: optional Vimscript configuration in `.vimrc` or `.gvimrc`:

```vim
let g:neovim_tour_codex_cmd = ['codex', '--no-daemon']
let g:neovim_tour_width = 0.42
```

If a GUI-launched MacVim cannot find Codex, use its full executable path in
`g:neovim_tour_codex_cmd` or add it to MacVim's PATH.

For a custom wrapper, replace `codex_cmd` with its executable and argument list.
The launcher appends one initial prompt. Keep the Codex process local to the
terminal so its shell tools receive the connection variables. You can override
the `NeovimTourRange` and `NeovimTourNote` highlight groups in your colorscheme.

## Troubleshooting

- **`:Codex` is unknown:** restart your editor after installation. In an existing
  session, run `:packadd neovim-tour`. Check that your package path matches the
  installer's `--nvim-data-dir` or `--vim-dir`.
- **Codex rejects `--no-daemon`:** update Codex. For an older version that always
  runs locally, configure `codex_cmd = { "codex" }`.
- **Skill is missing:** check `~/.agents/skills/neovim-tour/SKILL.md` and restart
  Codex. The installation is user-wide; no project files are needed.
- **Socket access fails:** the Codex shell must be allowed to reach the local
  Unix socket. Use the normal approval flow if your sandbox restricts it; the
  plugin does not weaken your sandbox or approval settings.
- **MacVim connection fails:** start from the MacVim GUI, where its native remote
  server runs. `:echo v:servername` should be nonempty. `:Codex` binds the exact
  MacVim executable and server; avoid substituting `/usr/bin/vim`.
- **Tab already contains a diff:** finish that comparison first or use another
  tab. Both editors share one diff group per tab, so the helper refuses to join an
  unrelated comparison.

## Uninstall

Before moving or removing the checkout:

```sh
python3 install.py --uninstall
python3 install.py --editor macvim --uninstall
python3 install.py --editor both --uninstall
```

Select the editors you want to remove and use the same custom directory flags
you used to install. Shared links remain while the other editor is still
installed at the supplied/default paths. Only links to this checkout are
removed; the source and existing configuration remain.

## Develop

```sh
python3 -m unittest discover -s tests -v
```

The tests use real editor processes and temporary Git repositories to verify
focus, unsaved buffers, annotations, comparisons, terminal environment handoff,
and installation. They do not invoke a model or require API credentials.

To exercise the Vimscript backend without opening any GUI windows, use terminal
Vim 9.2+ compiled with `+socketserver`:

```sh
VIM_TEST_BINARY=/path/to/terminal/vim python3 -m unittest discover -s tests -v
```

These tests run Vim in silent Ex mode with its socket transport. They do not
need a display or take desktop focus. Without a compatible terminal binary,
these backend tests are skipped; Neovim and installer tests still run.

MacVim's native transport requires its GUI. Its additional GUI integration suite
is **opt-in**, because it opens editor windows and can take desktop focus. Run
it manually when ready:

```sh
MACVIM_GUI_TESTS=1 MACVIM_BINARY=/Applications/MacVim.app/Contents/MacOS/Vim \
  python3 -m unittest discover -s tests -p test_macvim.py -v
```

Normal test discovery never launches MacVim GUI instances.

MIT licensed.
