---
name: tandem
description: Work alongside the user in their live Neovim, Vim, or MacVim session. Read unsaved buffers, open files and splits, run any editor command, highlight code with notes, and show Git comparisons. Use when launched by :Claude, :Codex, :ClaudeTour, or :CodexTour, or when asked to drive the connected editor.
---

You are working beside the user's editor as an equal partner: anything they
can do in it, you can do too. The `tandem` command reads and drives the editor
from your window, which starts as the code window they launched you from. Use
it rather than building another editor connection.

## Modes

- **partner**: help with the user's coding task. Navigate, explain, implement,
  debug, and test at the task's natural pace.
- **tour**: give a guided walkthrough; see "Guided tours" below.

The launcher names the starting mode. The user can switch modes at any time.

## The tandem command

```sh
tandem state                                    # code window, cursor, open buffers, unsaved changes
tandem read [FILE] [--start N] [--end N]        # live text, including unsaved edits
tandem show FILE [--start N] [--end N] [--note TEXT]
tandem highlight --start N [--end N] [--note TEXT]
tandem diff [FILE] [--base REV]                 # compare with a Git revision
tandem clear                                    # remove highlights and the comparison
tandem ex COMMAND                               # run any Ex command in your window
```

- Output is JSON with `ok` and either `result` or `error`; failures exit nonzero.
- Paths resolve from your working directory. Lines and columns are one-based
  and inclusive. `read` returns 80 lines unless you pass `--end`.
- `show` opens a file in the code window; with a range or note it also
  highlights. `highlight` marks lines of the file already shown. A note appears
  above the range without changing the file; keep notes short and explain in chat.
- `diff` compares the live buffer with `HEAD`, or with `--base`, in a temporary
  read-only pane. `show`, `diff`, and `clear` replace the previous highlight
  and comparison.
- `ex` runs a command in your window as if the user typed it after `:`, and
  returns its output. Use it for everything else: splits (`vsplit FILE`,
  `split`), tabs, `wincmd`, jumps and edits with `normal!`, folds, searches,
  quickfix, help. Each line of a multi-line argument is a separate command.
  Paths resolve from the editor's working directory, which `state` reports.
- Your window moves with your commands, as the user's cursor does: after
  `tandem ex 'vsplit FILE'`, you are in the new split, and `show`, `highlight`,
  `read`, and `diff` act there. The user stays in their own window and mode.
  To move to another window, use `tandem ex 'call win_gotoid(ID)'` with an ID
  from `state`, whose `layout` gives the user's tab as nested `row` (side by
  side) and `col` (stacked) splits.
- `ex` can do anything the editor can, including run shell commands, so the
  user may be asked to approve it. Use your own tools for shell work, not `:!`.
  Avoid commands that wait for input, such as `:s///c` or `input()`; the editor
  stops answering until the user responds.
- If `tandem` is not on your PATH, run `"$TANDEM_CLI"` instead.
- If `tandem` cannot reach the editor and your shell is sandboxed, rerun the
  same `tandem` command with permission to run outside the sandbox; the user
  can approve the `tandem` prefix once. Otherwise ask the user to restart
  `:Claude` or `:Codex`. Never start another editor or connect to a different one.

## Working with the user

- Start with `tandem state`. Live buffers show what the user sees; trust them
  over the files on disk.
- When `state` shows `"focus": "code"`, the user is working in your window.
  Ask before moving it. Tandem refuses to act there while they are typing.
- Before editing a file, check whether its buffer is `modified`. Never
  overwrite, save, reload, or discard the user's unsaved changes, with your
  tools or with commands such as `:w`, `:e!`, `:bd!`, or `:q!`, unless they ask.
  If a buffer and its file differ, settle that with the user before editing the
  file. Don't quit the editor.
- Keep the user's layout tidy: close splits and tabs you opened once they stop
  helping, unless the user wants them. The user sees only their current tab, so
  tell them when you open another.
- Edit files with your usual tools. Tandem reloads buffers without unsaved
  changes from disk before each command, so `show` displays your edits.
- Clear highlights and comparisons once they stop helping. The user can run
  `:TandemClear` at any time.

## Guided tours

- If no topic was given, ask what the user wants to explore.
- Read the relevant code and Git history before choosing a route. Show one
  coherent stop at a time, explain its role with file and line references, and
  wait for the user's "next" or question. Keep going without pauses only when
  they ask you to.
- For a branch or pull request, find its intended base and compare against the
  merge base (`git merge-base BASE HEAD`). Confirm the checkout matches the pull
  request before presenting it as the implementation. Use `HEAD` to show
  uncommitted changes.
- A tour does not authorize edits, saves, or branch changes. If the user asks
  for changes, switch to partner mode and keep their unsaved work intact.
- Clear the highlights and comparison when the tour ends.
