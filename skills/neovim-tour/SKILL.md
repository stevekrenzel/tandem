---
name: neovim-tour
description: Work alongside the user in a live Neovim, Vim, or MacVim session, inspecting unsaved buffers, navigating files, highlighting code, and showing Git comparisons. Use when launched with :Codex, :Claude, :CodexTour, or :ClaudeTour, or asked to control the connected editor.
---

You are connected to the user's editor. Use its bundled helper for editor
operations; do not build another server or RPC client. These instructions work
with both Codex and Claude Code.

## Session mode

The launcher supplies `NEOVIM_TOUR_MODE` and names the mode in the initial prompt:

- `partner`: collaborate on the user's coding task. Navigate, inspect, explain,
  implement, debug, and test as needed. Work at the task's natural pace.
- `tour`: read [references/tour.md](references/tour.md) for walkthrough pacing and
  comparisons before starting.

The user can change modes in conversation. If no mode was supplied, follow their
request; do not assume that every editor session is a tour.

## Connect and inspect

Run the helper as `"$NEOVIM_TOUR_CLI"`. If that variable is unavailable, use the
absolute path to `scripts/nvim-tour` beside this file. It uses Bash and the
editor's built-in remote client. Editor responses are JSON with `ok` and either
`result` or `error`; failures have a nonzero exit code. Usage and connection
failures go to stderr.

Start with the editor's state, then read live text when its contents matter:

```sh
"$NEOVIM_TOUR_CLI" state
"$NEOVIM_TOUR_CLI" read --start 1 --end 100
```

State identifies the source window, cursor, nearby text, open buffers, and unsaved
changes. Treat live buffers as the source of truth for what the user is seeing.
If no task was supplied, inspect state and ask what they want to work on.

The launcher selects the exact editor executable, server, and code window. If the
connection is missing or the target closes, explain that the user should restart
`:Codex` or `:Claude` from a code window. Do not guess another session or start a
second editor. MacVim uses its GUI's native server.

## Work in the editor

Use the existing code pane to show what you are discussing, preserving terminal
focus:

```sh
"$NEOVIM_TOUR_CLI" show src/example.py --line 24 --end 38 --note "Request entry"
"$NEOVIM_TOUR_CLI" highlight 45 --end 53 --note "Retry handling"
"$NEOVIM_TOUR_CLI" diff src/example.py --base HEAD
"$NEOVIM_TOUR_CLI" clear
```

Paths resolve from the calling shell's working directory. Line numbers are
one-based and inclusive. `read` includes unsaved changes and defaults to 80 lines.
`diff` defaults to the current source file and `HEAD`, with a temporary read-only
baseline. `show` or `clear` removes the previous comparison. Annotations do not
edit source text; keep notes short and put explanations in chat.

Use your normal coding tools for requested edits and tests. Before editing a
file, inspect its live-buffer state. Do not overwrite unsaved editor changes or
silently save, reload, or discard them. If the buffer has diverged from disk,
resolve that with the user before editing its disk copy. After editing an
unmodified file on disk, show the changed location and verify the live view
reflects it; do not claim that disk edits have appeared in the editor without
checking. If the view is stale, explain that `:checktime` can reload unmodified
buffers. The helper navigates and inspects buffers; it does not write or reload
them.

Clear temporary annotations and comparison panes when they are no longer useful.
The user can run `:TourClear` to clear all sessions' annotations and comparisons.
