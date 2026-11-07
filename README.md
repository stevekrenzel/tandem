# Neovim Tour

Run Codex or Claude Code beside your code in a Neovim, Vim, or MacVim terminal
split. Work together on coding tasks, or start a guided walkthrough. Both agents
can inspect live buffers, open files, highlight code, and show Git comparisons.

The plugin uses the editor's built-in remote client and loads the bundled
instructions when you start either agent. No extra server, global skill installation,
Python, Node package, or build step is needed for this plugin.

## Install

You need Bash, either [Codex CLI](https://learn.chatgpt.com/docs/cli/reference)
(with `--no-daemon` support) or [Claude Code](https://code.claude.com/docs/en/cli-reference)
on PATH, and either:

- Neovim 0.11+ on macOS or Linux.
- MacVim/Vim 9.1+ with `+clientserver`, `+terminal`, and `+textprop`. Terminal Vim
  also needs a working remote transport, such as Vim 9.2's `+socketserver`.

Git is needed for comparisons. Authenticate with your chosen agent before
starting a session. You only need the CLI you plan to use.

### Plugin manager

Use your usual plugin manager; there are no install hooks or required setup calls.
These examples use this local checkout. Once you publish the repository, replace
its local path with `YOUR_GITHUB_USER/neovim-tour`.

[lazy.nvim](https://lazy.folke.io/spec) (Neovim):

```lua
{
  dir = vim.fn.expand("~/Projects/neovim-tour"),
  cmd = { "Codex", "CodexTour", "Claude", "ClaudeTour", "TourClear" },
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
checkout in place while installed. No editor or agent configuration is changed.

## Work with an agent

Start from a code window:

| Command | Session |
| --- | --- |
| `:Codex [prompt]` | Codex coding partner |
| `:Claude [prompt]` | Claude Code coding partner |
| `:CodexTour [topic]` | Guided walkthrough with Codex |
| `:ClaudeTour [topic]` | Guided walkthrough with Claude Code |

For example:

```vim
:Codex Help me fix this failing test
:Claude Explain this function and suggest a simpler implementation
:CodexTour Walk me through this branch's changes
:ClaudeTour Show how authentication works, one stop at a time
```

All four commands open a terminal on the right, connected to the original code
window. Without a prompt, the agent inspects the editor and asks what you want
to work on. Partner sessions work at the task's natural pace; tour sessions pause
between stops so you can say “next” or ask questions. You can change modes in chat.

Both agents use the same editor-control helper. Their normal coding tools handle
file edits and tests; the helper reads and navigates live buffers without writing
them. The bundled instructions tell the agent to check for unsaved text before
editing and verify the live view after disk changes. Vim may need `:checktime`
to reload an unmodified buffer after a disk edit; the helper does not reload it.
Tour mode does not authorize source edits or saves.

Notes and highlighting do not edit source text. Navigation preserves unsaved
buffers, suppresses navigation-triggered autosave hooks, and keeps the agent's
terminal focused. File-loading and syntax events still run normally.

Run `:TourClear` to remove all annotations and temporary comparison panes, in
either mode. Close the terminal split normally when finished. Each source window
has its own session; start an agent from another code window to change targets.

For a PR walkthrough, have the PR's code checked out locally and identify its
intended base. The plugin does not automatically check out or fetch PRs.

## Configure

Defaults work without configuration. Optional Vimscript settings work in both editors:

```vim
let g:neovim_tour_codex_cmd = ['codex', '--no-daemon']
let g:neovim_tour_claude_cmd = ['claude']
let g:neovim_tour_width = 0.42
```

Neovim also supports Lua configuration, including lazy.nvim's `opts`:

```lua
require("neovim_tour").setup({ width = 0.42 })
```

Use an absolute executable path if a GUI-launched MacVim cannot find your agent.
Both modes use the corresponding agent command. A custom command receives one
appended initial prompt. Keep the process local so its shell tools inherit the
connection variables; `--no-daemon` does this for Codex. Claude uses its normal
interactive CLI. The plugin leaves each agent's permission and model settings
alone. The highlight groups are `NeovimTourRange` and `NeovimTourNote`.

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

For use outside the agent split, call `skills/neovim-tour/scripts/nvim-tour` from
this checkout with `--editor neovim|vim|macvim --server ADDRESS --window ID` before
the command. `:echo v:servername` shows the server address; `:echo win_getid()`
shows the code window ID. The helper refuses a closed or special-buffer target.

## Troubleshooting

- **An agent command is unknown:** restart the editor, load the plugin with your manager,
  or use `:packadd neovim-tour` for a native package. With lazy loading, include
  all four agent commands in the plugin spec as shown above.
- **Agent executable is missing:** install that CLI and sign in, or set its
  `g:neovim_tour_codex_cmd` / `g:neovim_tour_claude_cmd` to an absolute path.
- **Codex rejects `--no-daemon`:** update Codex or configure an older CLI that runs
  locally with `g:neovim_tour_codex_cmd = ['codex']`.
- **Connection fails:** start with `:Codex` or `:Claude` from a code window. MacVim's native
  server needs its GUI; terminal Vim needs a compatible remote transport.
  The launcher binds the exact running editor executable, avoiding system Vim.
  The agent's shell must be allowed to access the local editor socket through its
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

Tests use real headless editors, temporary Git repositories, and fake agent
processes. They never call a model or require credentials. For Vim coverage,
set `VIM_TEST_BINARY=/path/to/vim` to a terminal Vim with `+socketserver`.
Normal discovery never opens GUI windows. MacVim native GUI tests are explicitly
opt-in via `MACVIM_GUI_TESTS=1 MACVIM_BINARY=/path/to/MacVim.app/Contents/MacOS/Vim`.

MIT licensed.
