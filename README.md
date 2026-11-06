# Neovim Tour

Run Codex in a Neovim terminal split and let it walk you through the code beside it.
Codex can open files, point out a range, add temporary notes, and compare the live
buffer with a Git revision while you keep chatting in the terminal.

The connection uses Neovim's existing RPC socket and built-in remote client. A
global Codex skill teaches the walkthrough workflow; the bundled helper handles
the editor operations. There is no extra server to run or Python package to install.

## Install

Requirements: macOS or Linux, Neovim 0.11+, Python 3.9+, and a current Codex CLI
with `--no-daemon` support on your PATH. Git is needed for comparisons. Authenticate
with Codex normally before launching a tour.

From this checkout:

```sh
python3 install.py
```

The installer creates three symlinks:

| Component | Default location |
| --- | --- |
| Neovim plugin | `~/.local/share/nvim/site/pack/neovim-tour/start/neovim-tour` |
| Codex skill | `~/.agents/skills/neovim-tour` |
| Optional shell command | `~/.local/bin/nvim-tour` |

It does not edit `init.vim`, `init.lua`, or Codex settings. Existing destinations
are checked before installation and are never overwritten. Running it again is
safe. The plugin path honors `XDG_DATA_HOME` and `NVIM_APPNAME`; use
`--nvim-data-dir`, `--skill-dir`, and `--bin-dir` for custom locations.

Keep this checkout where you installed it, since the links point here. To share
it, send or publish the repository; each person runs the installer in their own
checkout. No machine-specific paths or credentials are stored in the source.

## Take a tour

Open a fresh Neovim session in your project, then run this from a code window:

```vim
:Codex Walk me through how authentication works
```

Or run `:Codex` and choose the topic in chat. The command opens a terminal on the
right, passes the socket and original code window to Codex, and invokes the skill.
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
added file has an empty baseline. The baseline buffer is temporary and read-only.

For a branch comparison, use its merge-base with the intended base branch:

```sh
base=$(git merge-base HEAD main)
"$NEOVIM_TOUR_CLI" diff src/server.py --base "$base"
```

To connect from an external shell, use explicit connection flags:

```sh
nvim-tour --server /path/to/nvim/socket --window 1000 state
```

Inside Neovim, `:echo v:servername` shows the socket and `:echo win_getid()` shows
the current window ID. The helper fails if the target closes or becomes a special
buffer. It does not guess a different window or editor.

## Configure

Optional Lua configuration (in `init.lua`, or a `lua` block in `init.vim`):

```lua
require("neovim_tour").setup({
  codex_cmd = { "codex", "--no-daemon" },
  width = 0.42, -- Fraction of the two-pane width used by the terminal.
})
```

For a custom wrapper, replace `codex_cmd` with its executable and argument list.
The launcher appends one initial prompt. Keep the Codex process local to the
terminal so its shell tools receive the connection variables. You can override
the `NeovimTourRange` and `NeovimTourNote` highlight groups in your colorscheme.

## Troubleshooting

- **`:Codex` is unknown:** restart Neovim after installation. In an existing
  session, run `:packadd neovim-tour`. Check that your package path matches the
  installer's `--nvim-data-dir`.
- **Codex rejects `--no-daemon`:** update Codex. For an older version that always
  runs locally, configure `codex_cmd = { "codex" }`.
- **Skill is missing:** check `~/.agents/skills/neovim-tour/SKILL.md` and restart
  Codex. The installation is user-wide; no project files are needed.
- **Socket access fails:** the Codex shell must be allowed to reach the local
  Unix socket. Use the normal approval flow if your sandbox restricts it; the
  plugin does not weaken your sandbox or approval settings.
- **Code pane is already in diff mode:** finish that diff first. The helper
  refuses to replace an unrelated comparison.

## Uninstall

Before moving or removing the checkout:

```sh
python3 install.py --uninstall
```

Use the same custom directory flags if you used them to install. Only links to
this checkout are removed; the source and existing configuration remain.

## Develop

```sh
python3 -m unittest discover -s tests -v
```

The tests use real headless Neovim instances and temporary Git repositories to
verify focus, unsaved buffers, annotations, comparisons, terminal environment
handoff, and installation. They do not invoke a model or require API credentials.

MIT licensed.
