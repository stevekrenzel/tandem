---
name: neovim-tour
description: Guide a code tour or pull request walkthrough in a live Neovim or MacVim session, opening files, highlighting code, and showing Git diffs while chatting in its Codex terminal. Use when launched with :Codex or asked to walk through code in either editor.
---

Use the bundled helper to control the connected editor. The launcher supplies the
editor connection, code window, and helper path; do not build another server or RPC client.

Run the helper as `"$NEOVIM_TOUR_CLI"` when that variable is available. Otherwise
use the absolute path to `scripts/nvim-tour` beside this skill. It requires Python
3.9+ and Neovim 0.11+ or MacVim with Vim 9.1+. Every response is JSON: `{ "ok": true, "result": ... }` or
`{ "ok": false, "error": ... }` with a nonzero exit code.

## Connect and orient

Start with:

```sh
"$NEOVIM_TOUR_CLI" state
```

This identifies the code pane, its cursor, nearby source, open buffers, unsaved
changes, and other windows. Read the live buffer when its contents matter:

```sh
"$NEOVIM_TOUR_CLI" read --start 1 --end 100
```

If the connection or window is missing, explain that the user should launch `:Codex`
from the code window. A closed target is an error, not permission to guess another
editor. An explicitly selected connection can use global flags before the command:
`nvim-tour --server /path/to/socket --window 1000 state` for Neovim, or
`nvim-tour --editor macvim --server VIM --window 1000 state` for MacVim. The
launcher selects the backend and exact editor executable automatically. MacVim
uses its GUI's native server; don't start a second editor to find a connection.

## Give the walkthrough

Inspect the relevant code and Git changes before choosing a useful route. Open the
first stop in the existing code pane and explain its role, using concrete file and
line references. Keep the Codex terminal focused; the helper does this for you.

```sh
"$NEOVIM_TOUR_CLI" show src/example.py --line 24 --end 38 --note "The request enters here"
"$NEOVIM_TOUR_CLI" highlight 45 --end 53 --note "This branch handles retries"
```

Paths resolve from the shell's working directory. Line numbers are one-based and
inclusive. Both backends use editor-native highlighting and virtual notes, not source edits.
Keep notes short; put the explanation in chat.

By default, show one coherent stop, explain it, and wait for the user's next step
or question. Do not race through several visible locations in one turn. Adapt the
pace if the user asks for an uninterrupted tour. If the launcher prompt gives no
topic, inspect state and ask what they want to explore.

For a branch or PR tour, identify the intended base from Git/PR metadata and use
the merge-base commit for the comparison. Confirm the checkout matches the PR
before claiming the visible files are its implementation. For local uncommitted
changes, comparing with `HEAD` is appropriate.

```sh
"$NEOVIM_TOUR_CLI" diff src/example.py --base <commit-sha>
```

The baseline opens beside the live buffer; unsaved changes remain visible. `show`
or `clear` removes the previous tour diff. Do not check out another revision,
overwrite buffers, or save files as part of a walkthrough. If the user requests
an edit, treat it as that explicit editing task, preserving their unsaved work.

When the tour is finished, clear its annotations and temporary diff pane:

```sh
"$NEOVIM_TOUR_CLI" clear
```

The user can also run `:TourClear` to clean up all tours in this editor.
