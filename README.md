# Neovim Tour

Run Codex in a Neovim, Vim, or MacVim terminal split and let it walk you through
the code beside it. Open files, highlight ranges, add temporary notes, and compare
the live buffer with a Git revision while chatting in the terminal.

The plugin uses the editor's built-in remote client and loads its bundled Codex
instructions when you run `:Codex`. No extra server, global skill installation,
Python, Node package, or build step is needed for this plugin.

## Install

You need Bash, Codex CLI on PATH with `--no-daemon` support, and either:

- Neovim 0.11+ on macOS or Linux.
- MacVim/Vim 9.1+ with `+clientserver`, `+terminal`, and `+textprop`. Terminal Vim
  also needs a working remote transport, such as Vim 9.2's `+socketserver`.

Git is needed for comparisons. Authenticate with Codex before starting a tour.

### Plugin manager

Use your usual plugin manager; there are no install hooks or required setup calls.
These examples use this local checkout. Once you publish the repository, replace
its local path with `YOUR_GITHUB_USER/neovim-tour`.

[lazy.nvim](https://lazy.folke.io/spec) (Neovim):

```lua
{
  dir = vim.fn.expand("~/Projects/neovim-tour"),
  cmd = { "Codex", "TourClear" },
  -- Optional: main = "neovim_tour", opts = { width = 0.42 },
}
```

For a published repository, replace `dir = ...` with `"YOUR_GITHUB_USER/neovim-tour"`.

[vim-plug](https://github.com/junegunn/vim-plug) (Vim, MacVim, or Neovim), inside
`plug#begin()` / `plug#end()`:

```vim
Plug '~/Projects/neovim-tour'
```

[packer.nvim](https://github.com/wbthomason/packer.nvim) (Neovim), inside its startup function:

```lua
use { vim.fn.expand("~/Projects/neovim-tour") }
```

The standard `plugin/`, `autoload/`, and `lua/` layout also works with native
packages and other managers that add plugins to `runtimepath`.

### Without a plugin manager

From this checkout:

```sh
./install.sh                 # Neovim
./install.sh --editor vim    # Vim or MacVim (--editor macvim also works)
./install.sh --editor both   # Both
```

The script creates one package symlink per editor:

| Editor | Default package location |
| --- | --- |
| Neovim | `~/.local/share/nvim/site/pack/neovim-tour/start/neovim-tour` |
| Vim / MacVim | `~/.vim/pack/neovim-tour/start/neovim-tour` |

It checks all destinations before making changes and never replaces existing
files. Re-running it is safe. Neovim paths honor `XDG_DATA_HOME` and `NVIM_APPNAME`;
use `--nvim-data-dir DIR` or `--vim-dir DIR` for custom locations. Keep this
checkout in place while installed. No editor or Codex configuration is changed.

## Take a tour

From a code window:

```vim
:Codex Walk me through how authentication works
```

Or run `:Codex` and choose a topic in chat. Codex opens on the right, connected
to the original code window. Say “next” to advance or ask a question at any stop.
For a PR walkthrough, have the PR's code checked out locally and ask Codex to
compare it with the intended base.

Notes and highlighting do not edit source text. Navigation preserves unsaved
buffers, suppresses navigation-triggered autosave hooks, and keeps the Codex
terminal focused. File-loading and syntax events still run normally.

Run `:TourClear` to remove all tour annotations and temporary comparison panes.
Close the terminal split normally when finished. Each source window has its own
tour; start `:Codex` from another code window to change targets.

## Configure

Defaults work without configuration. Optional Vimscript settings work in both editors:

```vim
let g:neovim_tour_codex_cmd = ['codex', '--no-daemon']
let g:neovim_tour_width = 0.42
```

Neovim also supports Lua configuration, including lazy.nvim's `opts`:

```lua
require("neovim_tour").setup({ width = 0.42 })
```

Use an absolute Codex executable path if a GUI-launched MacVim cannot find it.
A custom command receives one appended initial prompt. Keep the process local
so its shell tools inherit the connection variables; `--no-daemon` does this for
current Codex. The highlight groups are `NeovimTourRange` and `NeovimTourNote`.

## Helper commands

The launcher supplies the bundled helper's absolute path:

```sh
"$NEOVIM_TOUR_CLI" state
"$NEOVIM_TOUR_CLI" read --start 20 --end 80
"$NEOVIM_TOUR_CLI" show src/server.py --line 24 --end 38 --note "Request entry"
"$NEOVIM_TOUR_CLI" highlight 45 --end 53 --note "Retry handling"
"$NEOVIM_TOUR_CLI" diff src/server.py --base HEAD
"$NEOVIM_TOUR_CLI" clear
```

Editor responses are JSON with `ok` and either `result` or `error`. Errors have
a nonzero exit status; usage and connection failures go to stderr. Paths resolve
from the calling shell's working directory. Line numbers are one-based and
inclusive. `read` includes unsaved text and defaults to 80 lines. `diff` defaults
to the current code buffer and `HEAD`; its baseline is temporary and read-only.
An added file gets an empty baseline; deleted files also work.

For use outside the Codex split, call `skills/neovim-tour/scripts/nvim-tour` from
this checkout with `--editor neovim|vim|macvim --server ADDRESS --window ID` before
the command. `:echo v:servername` shows the server address; `:echo win_getid()`
shows the code window ID. The helper refuses a closed or special-buffer target.

## Troubleshooting

- **`:Codex` is unknown:** restart the editor, load the plugin with your manager,
  or use `:packadd neovim-tour` for a native package.
- **Codex rejects `--no-daemon`:** update Codex or configure an older CLI that runs
  locally with `g:neovim_tour_codex_cmd = ['codex']`.
- **Connection fails:** start with `:Codex` from a code window. MacVim's native
  server needs its GUI; terminal Vim needs a compatible remote transport.
  The launcher binds the exact running editor executable, avoiding system Vim.
  Codex's shell must be allowed to access the local editor socket through its
  normal sandbox/approval settings.
- **Tab already contains a diff:** finish that comparison first or use another
  tab. The editor shares one diff group per tab.

## Uninstall

Remove the plugin through your plugin manager, or undo the shell installation:

```sh
./install.sh --uninstall
./install.sh --editor vim --uninstall
./install.sh --editor both --uninstall
```

Use the same custom directory flags as installation. Only links to this checkout
are removed. Older installations may also have links at `~/.agents/skills/neovim-tour`
and `~/.local/bin/nvim-tour`; they are no longer needed and can be removed.

## Develop

Python is used only for the development test suite:

```sh
python3 -m unittest discover -s tests -v
shellcheck install.sh skills/neovim-tour/scripts/nvim-tour
```

Tests use real headless editors, temporary Git repositories, and fake Codex
processes. They never call a model or require credentials. For Vim coverage,
set `VIM_TEST_BINARY=/path/to/vim` to a terminal Vim with `+socketserver`.
Normal discovery never opens GUI windows. MacVim native GUI tests are explicitly
opt-in via `MACVIM_GUI_TESTS=1 MACVIM_BINARY=/path/to/MacVim.app/Contents/MacOS/Vim`.

MIT licensed.
