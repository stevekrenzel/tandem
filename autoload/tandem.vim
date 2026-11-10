" Tandem runs a coding agent beside a code window. The agent drives the editor
" from its own window, which starts as that one, through the bundled `tandem`
" helper, which calls tandem#Command().

let s:root = fnamemodify(resolve(expand('<sfile>:p')), ':h:h')
let s:skill = s:root . '/skills/tandem/SKILL.md'
let s:helper = s:root . '/skills/tandem/scripts/tandem'
let s:sid = expand('<SID>')
let s:agents = {
      \ 'claude': {'name': 'Claude', 'command': ['claude']},
      \ 'codex': {'name': 'Codex', 'command': ['codex', '--no-daemon']}}
" Each code window that an agent works with has a session. Its key is normally
" its starting window's ID and stays fixed when the agent changes windows.
" A window whose ID is still another session's key gets a fresh negative key,
" which cannot collide with a window ID:
"   key, window: the session's key and its current code window
"   namespace (Neovim) or range_type and note_type (Vim): annotation storage
"   marked_buffer: the buffer that currently shows annotations
"   diff: {source, window, buffer} while a comparison is open
"   agent, mode, terminal: the agent, its mode, and its terminal buffer
let s:sessions = {}
let s:next_session_key = -1
" Moving the code window must not fire the user's autosave or focus hooks.
let s:navigation_events = ['BufLeave', 'BufWinLeave', 'BufEnter', 'BufWinEnter', 'WinLeave', 'WinEnter', 'FocusLost']
" Comparisons sit side by side when each side can keep 80 columns.
let s:side_by_side_width = 160

function! s:Highlights() abort
  highlight default link TandemRange Visual
  highlight default link TandemNote Special
endfunction
call s:Highlights()

augroup tandem
  autocmd!
  autocmd ColorScheme * call s:Highlights()
  " Closing windows inside WinClosed is not allowed, so clean up afterwards.
  autocmd WinClosed * call timer_start(0, function('s:WindowClosed', [str2nr(expand('<amatch>'))]))
augroup END
" Temporary autocommands that answer prompts which would block a request.
augroup tandem_prompts
augroup END

" ---------------------------------------------------------------- utilities

function! s:Require(condition, message) abort
  if !a:condition
    throw a:message
  endif
endfunction

" Drops the 'Vim(command):' prefix that built-in errors carry.
function! s:Message(exception) abort
  return substitute(a:exception, '^Vim\%((\a\+)\)\=:', '', '')
endfunction

function! s:Error(exception) abort
  let v:errmsg = 'Tandem: ' . s:Message(a:exception)
  echohl ErrorMsg
  echomsg v:errmsg
  echohl None
endfunction

" Calls a:Fn with navigation events suppressed and restores 'eventignore'.
function! s:Quietly(Fn) abort
  let previous = &eventignore
  if previous !=# 'all'
    let &eventignore = join(filter(split(previous, ',') + s:navigation_events, 'v:val !=# ""'), ',')
  endif
  try
    return a:Fn()
  finally
    let &eventignore = previous
  endtry
endfunction

function! s:IsCodeWindow(window) abort
  return win_id2tabwin(a:window) != [0, 0] && win_gettype(a:window) ==# ''
        \ && getbufvar(winbufnr(a:window), '&buftype') ==# ''
endfunction

" Window-ID lookups in getcwd() and getwinvar() only search the current tab, and
" the user may have switched tabs since the agent started.
function! s:Cwd(window) abort
  let [tab, number] = win_id2tabwin(a:window)
  return getcwd(number, tab)
endfunction

function! s:Path(buffer) abort
  let name = bufname(a:buffer)
  return name ==# '' ? '' : fnamemodify(name, ':p')
endfunction

" Returns the session working with a code window, or {}.
function! s:Find(window) abort
  for state in values(s:sessions)
    if state.window == a:window
      return state
    endif
  endfor
  return {}
endfunction

function! s:Session(window) abort
  let state = s:Find(a:window)
  if !empty(state)
    return state
  endif
  let key = string(a:window)
  if has_key(s:sessions, key)
    let key = string(s:next_session_key)
    let s:next_session_key -= 1
  endif
  let state = {'key': key, 'window': a:window}
  if has('nvim')
    let state.namespace = nvim_create_namespace('tandem:' . key)
  else
    let state.range_type = 'TandemRange_' . key
    let state.note_type = 'TandemNote_' . key
    if empty(prop_type_get(state.range_type))
      call prop_type_add(state.range_type, {'highlight': 'TandemRange', 'priority': 150, 'combine': 1})
      call prop_type_add(state.note_type, {'highlight': 'TandemNote', 'priority': 150})
    endif
  endif
  let s:sessions[key] = state
  return state
endfunction

function! s:Forget(state) abort
  if !has_key(s:sessions, get(a:state, 'key', ''))
    return
  endif
  call remove(s:sessions, a:state.key)
  try
    call s:ClearSession(a:state)
  finally
    if !has('nvim')
      call prop_type_delete(a:state.range_type)
      call prop_type_delete(a:state.note_type)
    endif
  endtry
endfunction

" ------------------------------------------------------- annotations, diffs

function! s:ClearMarks(state) abort
  if !has_key(a:state, 'marked_buffer')
    return
  endif
  let buffer = remove(a:state, 'marked_buffer')
  if bufloaded(buffer)
    if has('nvim')
      call nvim_buf_clear_namespace(buffer, a:state.namespace, 0, -1)
    else
      call prop_remove({'types': [a:state.range_type, a:state.note_type], 'bufnr': buffer, 'all': 1})
    endif
  endif
endfunction

function! s:CloseDiff(state) abort
  if !has_key(a:state, 'diff')
    return
  endif
  let diff = remove(a:state, 'diff')
  if win_id2tabwin(diff.source) != [0, 0]
    call win_execute(diff.source, 'diffoff')
  endif
  " Wiping the baseline closes its pane, even when it is the last window.
  if bufexists(diff.buffer)
    execute 'bwipeout!' diff.buffer
  endif
endfunction

" Removes a session's annotations and comparison. Callers suppress navigation
" events because closing the comparison pane changes windows.
function! s:ClearSession(state) abort
  call s:ClearMarks(a:state)
  call s:CloseDiff(a:state)
endfunction

function! s:Clear(window) abort
  call s:ClearSession(s:Find(a:window))
  return {'cleared': v:true}
endfunction

function! s:ClearAll() abort
  for state in values(s:sessions)
    call s:ClearSession(state)
  endfor
endfunction

function! tandem#ClearAll() abort
  call s:Quietly(function('s:ClearAll'))
endfunction

function! s:WindowClosed(window, ...) abort
  for state in values(s:sessions)
    if state.window == a:window
      " A running agent keeps its session until :Claude or :Codex gives it a
      " new code window.
      if s:AgentRunning(state)
        call s:Quietly({-> s:ClearSession(state)})
      else
        call s:Quietly({-> s:Forget(state)})
      endif
    elseif get(get(state, 'diff', {}), 'window', 0) == a:window
      " The user closed the comparison pane, so end the comparison.
      call s:Quietly({-> s:CloseDiff(state)})
    endif
  endfor
endfunction

" ------------------------------------------------------------------ launch

" Entry point for :Claude, :Codex, :ClaudeTour, and :CodexTour.
function! tandem#Launch(agent, mode, prompt, replace, range) abort
  try
    call s:Launch(a:agent, a:mode, a:prompt, a:replace, a:range)
  catch
    call s:Error(v:exception)
  endtry
endfunction

function! s:Launch(agent, mode, prompt, replace, range) abort
  call s:RequireEditor()
  let origin = [win_getid(), bufnr()]
  let window = s:LaunchTarget(a:agent)
  let state = s:Session(window)
  let ask = s:Ask(window, origin, a:range, a:prompt)
  if s:AgentRunning(state) && !a:replace
    call s:Require(state.agent ==# a:agent, printf('%s is already working with this window. Run :%s! to replace it.',
          \ s:agents[state.agent].name, s:agents[a:agent].name))
    if a:mode !=# state.mode
      let ask = join(filter(['Switch to ' . a:mode . ' mode.', ask], 'v:val !=# ""'))
    endif
    call s:Quietly({-> s:ShowAgent(state.terminal)})
    if ask !=# ''
      call s:Type(state.terminal, ask)
    endif
  else
    let width = s:Width()
    call s:StartServer()
    let command = s:AgentCommand(a:agent) + s:AgentArguments(a:agent, a:mode, ask ==# '' ? s:DefaultAsk(a:mode) : ask)
    if a:agent ==# 'codex'
      call s:WriteCodexRules()
    endif
    call s:Quietly({-> s:StartAgent(state, window, a:agent, command, width)})
  endif
  let state.mode = a:mode
  startinsert
endfunction

function! s:RequireEditor() abort
  if has('nvim')
    call s:Require(has('nvim-0.11'), 'Tandem needs Neovim 0.11 or newer.')
  else
    call s:Require(v:version >= 901 && has('clientserver') && has('terminal') && has('textprop'),
          \ 'Tandem needs Vim 9.1 or newer with +clientserver, +terminal, and +textprop.')
  endif
endfunction

" Picks the code window the agent will work with. A running agent whose code
" window was closed takes over the new one.
function! s:LaunchTarget(agent) abort
  " From an agent's pane, keep working with its code window.
  for state in values(s:sessions)
    if get(state, 'terminal', -1) == bufnr()
      if !s:IsCodeWindow(state.window)
        call s:Quietly({-> s:ClearSession(state)})
        let state.window = s:NewCodeWindow()
      endif
      return state.window
    endif
  endfor
  let window = s:CodeWindow()
  if !s:AgentRunning(s:Find(window))
    let orphans = filter(values(s:sessions), {_, state -> get(state, 'agent', '') ==# a:agent
          \ && win_id2tabwin(state.window) == [0, 0] && s:AgentRunning(state)})
    if !empty(orphans)
      call s:Forget(s:Find(window))
      let orphans[0].window = window
    endif
  endif
  return window
endfunction

function! s:CodeWindow() abort
  let candidates = [win_getid(), win_getid(winnr('#'))] + map(range(1, winnr('$')), 'win_getid(v:val)')
  for window in candidates
    if window && s:IsCodeWindow(window)
      return window
    endif
  endfor
  " Start screens, file explorers, and scratch buffers make way for an empty
  " buffer, but stay loaded whatever their 'bufhidden'.
  call s:Require(&buftype !=# 'terminal', 'Open a file in a window, then run the command again.')
  let [buffer, bufhidden] = [bufnr(), &bufhidden]
  setlocal bufhidden=hide
  try
    hide enew
  finally
    call setbufvar(buffer, '&bufhidden', bufhidden)
  endtry
  return win_getid()
endfunction

" Opens an empty code window beside the current agent pane, which keeps its width.
function! s:NewCodeWindow() abort
  let width = winwidth(0)
  leftabove vnew
  let window = win_getid()
  wincmd p
  execute 'vertical resize' width
  return window
endfunction

" Describes what the user asked for, including the lines they selected.
function! s:Ask(window, origin, range, prompt) abort
  let parts = []
  if !empty(a:range) && [a:window, winbufnr(a:window)] == a:origin
    let [first, last] = a:range
    let lines = first == last ? 'line ' . first : printf('lines %d-%d', first, last)
    let file = fnamemodify(bufname(winbufnr(a:window)), ':~:.')
    call add(parts, printf('Look at %s of %s.', lines, file ==# '' ? 'the current buffer' : file))
  endif
  if a:prompt !=# ''
    call add(parts, a:prompt)
  endif
  return join(parts)
endfunction

function! s:DefaultAsk(mode) abort
  return 'Inspect the code window and ask what I want to ' . (a:mode ==# 'tour' ? 'explore.' : 'work on.')
endfunction

function! s:AgentRunning(state) abort
  let buffer = get(a:state, 'terminal', -1)
  if !bufexists(buffer)
    return 0
  endif
  if has('nvim')
    return jobwait([getbufvar(buffer, '&channel')], 0)[0] == -1
  endif
  return term_getstatus(buffer) =~# 'running'
endfunction

function! s:ShowAgent(buffer) abort
  let windows = filter(win_findbuf(a:buffer), 'win_id2tabwin(v:val)[0] == tabpagenr()')
  if !empty(windows)
    call win_gotoid(windows[0])
    return
  endif
  botright vsplit
  execute 'buffer' a:buffer
  execute 'vertical resize' s:Width()
  " Splits elsewhere, the user's or the agent's, leave the pane's width alone.
  setlocal winfixwidth
endfunction

function! s:Type(buffer, text) abort
  if has('nvim')
    call chansend(getbufvar(a:buffer, '&channel'), a:text)
  else
    call term_sendkeys(a:buffer, a:text)
  endif
endfunction

function! s:Width() abort
  let width = get(g:, 'tandem_width', 0.42)
  call s:Require(index([v:t_number, v:t_float], type(width)) >= 0 && width > 0,
        \ 'g:tandem_width must be a fraction of the screen, such as 0.4, or a column count, such as 80.')
  let columns = width < 1 ? float2nr(&columns * width) : float2nr(width)
  return max([20, min([columns, &columns - 20])])
endfunction

function! s:StartServer() abort
  if v:servername ==# ''
    if has('nvim')
      call serverstart()
    else
      call remote_startserver('TANDEM_' . getpid())
    endif
  endif
  call s:Require(v:servername !=# '',
        \ 'No editor server. Start MacVim in its GUI, or terminal Vim with a remote transport such as +socketserver.')
endfunction

function! s:AgentCommand(agent) abort
  let variable = 'g:tandem_' . a:agent . '_cmd'
  let command = get(g:, 'tandem_' . a:agent . '_cmd', s:agents[a:agent].command)
  if type(command) == v:t_string
    let command = split(command)
  endif
  call s:Require(type(command) == v:t_list && !empty(command),
        \ printf('%s must be a command such as %s.', variable, string(s:agents[a:agent].command)))
  call s:Require(executable(command[0]), printf('%s executable was not found: %s. Install it or set %s.',
        \ s:agents[a:agent].name, command[0], variable))
  return copy(command)
endfunction

" Claude takes the instructions as a system prompt and its permission to run
" the helper as session settings, which add to the user's own settings.
" Codex has no per-session equivalent, so it reads the instructions file.
"
" Every tandem command is allowed. The helper runs outside Claude's sandbox
" rather than opening the editor's socket to it, so that only the helper can
" reach the editor.
function! s:AgentArguments(agent, mode, ask) abort
  if a:agent ==# 'claude'
    let settings = {'permissions': {'allow': ['Bash(tandem *)']}, 'sandbox': {'excludedCommands': ['tandem *']}}
    " After --, a prompt that starts with a dash is not read as an option.
    return ['--append-system-prompt', s:Instructions(a:mode), '--settings', json_encode(settings), '--', a:ask]
  endif
  return ['Read and follow ' . json_encode(s:skill) . '. Session mode: ' . a:mode . '. ' . a:ask]
endfunction

" Codex reads permission rules only from files, so Tandem writes one that lets
" `tandem` commands run outside its sandbox without asking. A file the user
" has, even an edited one, is left alone.
let s:codex_rules = [
      \ '# Written by Tandem (https://github.com/stevekrenzel/tandem) so that Codex can',
      \ '# run the `tandem` helper, which drives your editor, without asking.',
      \ '# To manage this file yourself, set g:tandem_codex_rules = 0.',
      \ 'prefix_rule(pattern=["tandem"], decision="allow")']
let s:codex_rules_error = ''

function! tandem#CodexRulesFile() abort
  return (empty($CODEX_HOME) ? expand('~/.codex') : $CODEX_HOME) . '/rules/tandem.rules'
endfunction

function! tandem#CodexRulesError() abort
  return s:codex_rules_error
endfunction

function! s:WriteCodexRules() abort
  let s:codex_rules_error = ''
  let path = tandem#CodexRulesFile()
  if !get(g:, 'tandem_codex_rules', 1) || filereadable(path)
    return
  endif
  try
    call mkdir(fnamemodify(path, ':h'), 'p')
    call writefile(s:codex_rules, path)
  catch
    let s:codex_rules_error = printf('Could not write %s: %s', path, s:Message(v:exception))
    echohl WarningMsg
    echomsg 'Tandem: ' . s:codex_rules_error
    echohl None
  endtry
endfunction

function! s:Instructions(mode) abort
  let lines = readfile(s:skill)
  if get(lines, 0, '') ==# '---'
    let lines = lines[index(lines, '---', 1) + 1 :]
  endif
  return trim(join(lines, "\n")) . "\n\nSession mode: " . a:mode . '.'
endfunction

" TANDEM_WINDOW names the session, which keeps its key when its window changes.
function! s:Environment(state) abort
  let env = {'TANDEM_SERVER': v:servername, 'TANDEM_WINDOW': a:state.key, 'TANDEM_CLI': s:helper,
        \ 'PATH': fnamemodify(s:helper, ':h') . ':' . $PATH}
  if has('nvim')
    let env.TANDEM_EDITOR = 'neovim'
    let env.TANDEM_EDITOR_BIN = v:progpath
  else
    let env.TANDEM_EDITOR = 'vim'
    let env.TANDEM_EDITOR_BIN = exepath(v:progpath)
    let backend = index(v:argv, '--clientserver')
    if backend >= 0
      let env.VIM_CLIENTSERVER = get(v:argv, backend + 1, '')
    endif
  endif
  return env
endfunction

function! s:StartAgent(state, window, agent, command, width) abort
  let options = {'cwd': s:Cwd(a:window), 'env': s:Environment(a:state)}
  let pane = {'state': a:state}
  botright vnew
  let placeholder = bufnr()
  try
    execute 'vertical resize' a:width
    setlocal winfixwidth
    if has('nvim')
      call extend(options, {'term': v:true, 'on_exit': function('s:AgentExited', [pane])})
      call s:Require(jobstart(a:command, options) > 0, 'Could not start ' . a:command[0] . '.')
      let pane.buffer = bufnr()
    else
      call extend(options, {'curwin': 1, 'exit_cb': function('s:AgentExited', [pane])})
      let pane.buffer = term_start(a:command, options)
      call s:Require(pane.buffer > 0, 'Could not start ' . a:command[0] . '.')
    endif
  catch
    execute 'bwipeout!' placeholder
    throw v:exception
  endtry
  if pane.buffer != placeholder && bufexists(placeholder)
    execute 'bwipeout' placeholder
  endif
  " Closing the pane hides the agent instead of ending it, even with 'nohidden'.
  call setbufvar(pane.buffer, '&bufhidden', 'hide')
  if has_key(a:state, 'terminal')
    " :Claude! replaces the running agent. A wiped agent may not have reported
    " its exit yet.
    call s:ClearSession(a:state)
    let previous = remove(a:state, 'terminal')
    if bufexists(previous)
      execute 'bwipeout!' previous
    endif
  endif
  let a:state.agent = a:agent
  let a:state.terminal = pane.buffer
endfunction

" When an agent exits, its annotations go too. A clean exit closes the pane;
" otherwise the pane stays open so the user can read what went wrong.
function! s:AgentExited(pane, job, status, ...) abort
  let state = a:pane.state
  if get(state, 'terminal', -1) == get(a:pane, 'buffer', -2)
    call remove(state, 'terminal')
    if win_id2tabwin(state.window) == [0, 0]
      " Its code window is gone too.
      call s:Quietly({-> s:Forget(state)})
    else
      call s:Quietly({-> s:ClearSession(state)})
    endif
  endif
  if a:status == 0
    call timer_start(0, {-> s:Wipe(get(a:pane, 'buffer', -1))})
  endif
endfunction

function! s:Wipe(buffer) abort
  if bufexists(a:buffer)
    call s:Quietly({-> execute('bwipeout! ' . a:buffer)})
  endif
endfunction

" ------------------------------------------------------- helper requests

let s:commands = {
      \ 'state': {'options': [], 'file': 'none'},
      \ 'read': {'options': ['start', 'end'], 'file': 'optional'},
      \ 'show': {'options': ['start', 'end', 'note'], 'file': 'required'},
      \ 'highlight': {'options': ['start', 'end', 'note'], 'file': 'none'},
      \ 'diff': {'options': ['base'], 'file': 'optional'},
      \ 'clear': {'options': [], 'file': 'none'},
      \ 'ex': {'options': [], 'file': 'none'}}
" Requests that work in any window. The rest need a window that shows a file.
let s:anywhere = ['state', 'clear', 'ex']

" Entry point for the helper, which names the agent's session. Returns the
" exit status on the first line and the JSON response on the second.
function! tandem#Command(argv, cwd, session) abort
  try
    let args = s:Parse(a:argv, a:cwd, a:session)
    let response = {'ok': v:true, 'result': s:Quietly({-> s:Run(args)})}
    let json = json_encode(response)
  catch
    let response = {'ok': v:false, 'error': s:Message(v:exception)}
    let json = json_encode(response)
  endtry
  return (response.ok ? '0' : '1') . "\n" . json
endfunction

function! s:Parse(argv, cwd, session) abort
  call s:Require(!empty(a:argv), 'A command is required. Run tandem --help.')
  let action = a:argv[0]
  call s:Require(has_key(s:commands, action), 'Unknown command: ' . action . '. Run tandem --help.')
  let spec = s:commands[action]
  let args = {'action': action, 'session': str2nr(a:session), 'file': v:null,
        \ 'start': v:null, 'end': v:null, 'note': '', 'base': 'HEAD'}
  if action ==# 'ex'
    " The command is everything after ex, as typed after : in the editor.
    let words = a:argv[1:]
    let args.command = join(get(words, 0, '') ==# '--' ? words[1:] : words)
    call s:Require(trim(args.command) !=# '', 'ex requires a command, such as: tandem ex vsplit other.py')
    return args
  endif
  let positional = []
  let rest = a:argv[1:]
  let literal = 0
  while !empty(rest)
    let argument = remove(rest, 0)
    if argument ==# '--' && !literal
      let literal = 1
    elseif argument =~# '^--' && !literal
      let name = matchstr(argument, '^--\zs[^=]*')
      call s:Require(index(spec.options, name) >= 0, printf('%s does not accept %s.', action, argument))
      if argument =~# '='
        let args[name] = matchstr(argument, '=\zs.*')
      else
        call s:Require(!empty(rest), 'Missing value for ' . argument . '.')
        let args[name] = remove(rest, 0)
      endif
    else
      call add(positional, argument)
    endif
  endwhile
  if spec.file ==# 'none'
    call s:Require(empty(positional), action . ' does not take a file.')
  else
    call s:Require(len(positional) <= 1, action . ' takes one file.')
    call s:Require(spec.file ==# 'optional' || len(positional) == 1, action . ' requires a file.')
  endif
  if !empty(positional)
    let file = positional[0] =~# '^\~/' ? expand('~') . positional[0][1:] : positional[0]
    let args.file = simplify(file =~# '^/' ? file : a:cwd . '/' . file)
  endif
  for name in ['start', 'end']
    if args[name] isnot v:null
      call s:Require(args[name] =~# '^\d\+$' && str2nr(args[name]) > 0, '--' . name . ' must be a positive line number.')
      let args[name] = str2nr(args[name])
    endif
  endfor
  call s:Require(action !=# 'highlight' || args.start isnot v:null, 'highlight requires --start.')
  return args
endfunction

function! s:Run(args) abort
  let action = a:args.action
  let window = s:Target(a:args.session, action)
  call s:Refresh(winbufnr(window))
  " Insert mode, a half-typed command, or a pending operator would land in
  " whatever the code window shows next.
  if index(['show', 'highlight', 'diff', 'ex'], action) >= 0
    call s:Require(win_getid() != window || mode(1) ==# 'n',
          \ 'The user is typing in the code window. Wait, or ask before moving it.')
  endif
  if action ==# 'state'
    return s:State(window)
  endif
  " Loading a hidden buffer, as bufload() and setbufvar() do, from a focused
  " Neovim terminal resizes that terminal to the whole screen. Act from the
  " code window instead. The user's own window and mode stay as they were.
  let result = v:null
  let s:ex_window = 0
  let [user, previous] = [win_getid(), win_getid(winnr('#'))]
  try
    call win_execute(window, 'let result = ' . s:sid . 'Act(window, a:args)')
  finally
    " Like the user's cursor, the agent's window moves with its commands,
    " even ones that fail partway.
    if s:ex_window
      let window = s:Follow(window, s:ex_window)
    endif
    call s:KeepPrevious(user, previous)
  endtry
  if action ==# 'ex'
    let result.window = window
    let result.file = s:Path(winbufnr(window))
    let result.cursor = getcurpos(window)[1:2]
  endif
  return result
endfunction

" Runs inside the agent's window, as if the user had typed the command there.
" Each line is a separate command. Output is captured instead of shown.
function! s:Ex(command) abort
  try
    let output = execute(split(a:command, "\n"), 'silent')
  finally
    let s:ex_window = win_getid()
  endtry
  return {'output': substitute(output, '^\n\+', '', '')}
endfunction

" Moves a session to the window its command ended in, unless that window is
" a terminal, a floating or special window, or another agent's. Returns the
" session's window.
function! s:Follow(window, final) abort
  if a:final == a:window
    return a:window
  endif
  let state = s:Session(a:window)
  if win_id2tabwin(a:window) == [0, 0]
    " WinClosed runs later, after the session has moved. Clean up now; the
    " destination may itself be the comparison pane that cleanup closes.
    call s:ClearSession(state)
    if win_id2tabwin(a:final) == [0, 0]
      return s:Replacement(state)
    endif
  endif
  if !s:CanWorkIn(a:final)
    return a:window
  endif
  let other = s:Find(a:final)
  if !empty(other) && other isnot state
    return a:window
  endif
  let state.window = a:final
  return a:final
endfunction

" Switching windows inside win_execute() changes the window that the user's
" CTRL-W p goes back to. Restore it; the user stays in their window and mode.
function! s:KeepPrevious(user, previous) abort
  if a:previous == 0 || win_getid() != a:user || win_getid(winnr('#')) == a:previous
        \ || win_id2tabwin(a:previous)[0] != tabpagenr()
    return
  endif
  noautocmd call win_gotoid(a:previous)
  noautocmd call win_gotoid(a:user)
endfunction

" Whether an agent can work in a window: any ordinary window but a terminal.
function! s:CanWorkIn(window) abort
  return win_id2tabwin(a:window) != [0, 0] && win_gettype(a:window) ==# ''
        \ && getbufvar(winbufnr(a:window), '&buftype') !=# 'terminal'
endfunction

function! s:Act(window, args) abort
  if a:args.action ==# 'ex'
    return s:Ex(a:args.command)
  elseif a:args.action ==# 'read'
    return s:Read(a:window, a:args.file, a:args.start, a:args.end)
  elseif a:args.action ==# 'show'
    return s:Show(a:window, a:args.file, a:args.start, a:args.end, a:args.note)
  elseif a:args.action ==# 'highlight'
    return s:Annotate(a:window, a:args.start, a:args.end, a:args.note)
  elseif a:args.action ==# 'diff'
    return s:Diff(a:window, a:args.file, a:args.base)
  endif
  return s:Clear(a:window)
endfunction

" Returns a session's code window. Without a session, the key is a window ID.
function! s:Target(key, action) abort
  let state = get(s:sessions, string(a:key), {})
  let window = get(state, 'window', a:key)
  if win_id2tabwin(window) == [0, 0] && s:AgentRunning(state)
    let window = s:Replacement(state)
  endif
  let command = has_key(state, 'agent') ? ':' . s:agents[state.agent].name : ':Claude or :Codex'
  call s:Require(win_id2tabwin(window) != [0, 0],
        \ 'The code window was closed. Ask the user to run ' . command . ' to give you a new one.')
  call s:Require(index(s:anywhere, a:action) >= 0 || s:IsCodeWindow(window),
        \ 'The code window is showing a terminal or special buffer. Use tandem ex to move to a file''s window.')
  return window
endfunction

" When the user closes an agent's window, the agent moves to the window the
" user is in, the one they were in before, or another file's window, in the
" tab that shows the agent. Returns 0 if there is none.
function! s:Replacement(state) abort
  let panes = win_findbuf(get(a:state, 'terminal', -1))
  let tab = empty(panes) ? tabpagenr() : win_id2tabwin(panes[0])[0]
  let candidates = [win_getid(), win_getid(winnr('#'))] + map(getwininfo(), 'v:val.winid')
  for window in candidates
    if window && win_id2tabwin(window)[0] == tab && s:IsCodeWindow(window) && empty(s:Find(window))
      call s:Quietly({-> s:ClearSession(a:state)})
      let a:state.window = window
      return window
    endif
  endfor
  return 0
endfunction

" Reloads a buffer without unsaved changes when its file changed on disk, so
" the user sees the agent's edits. Buffers with unsaved changes are untouched.
function! s:Refresh(buffer) abort
  if !bufloaded(a:buffer) || getbufvar(a:buffer, '&modified') || getbufvar(a:buffer, '&buftype') !=# ''
        \ || bufname(a:buffer) ==# ''
    return
  endif
  " Answering the change prompt here keeps it from blocking the request.
  execute 'autocmd tandem_prompts FileChangedShell <buffer=' . a:buffer . '>'
        \ 'let v:fcs_choice = v:fcs_reason ==# "deleted" ? "" : "reload"'
  let ignored = &eventignore
  try
    let &eventignore = join(s:navigation_events, ',')
    silent! execute 'checktime' a:buffer
  finally
    let &eventignore = ignored
    autocmd! tandem_prompts
  endtry
endfunction

" Describes the editor: the agent's window, where the user is, every window
" with its file, position, and size, and the user's tab's layout.
function! s:State(window) abort
  let windows = []
  for info in getwininfo()
    call add(windows, {'id': info.winid, 'tab': info.tabnr, 'buffer': info.bufnr, 'file': s:Path(info.bufnr),
          \ 'cursor': getcurpos(info.winid)[1:2], 'row': info.winrow, 'col': info.wincol,
          \ 'width': info.width, 'height': info.height})
  endfor
  let buffers = []
  for info in getbufinfo({'bufloaded': 1})
    call add(buffers, {'id': info.bufnr, 'file': info.name, 'lines': info.linecount,
          \ 'modified': info.changed ? v:true : v:false, 'buftype': getbufvar(info.bufnr, '&buftype')})
  endfor
  let current = win_getid()
  let agent = get(s:Find(a:window), 'terminal', -1)
  let focus = current == a:window ? 'code' : winbufnr(current) == agent ? 'agent' : 'other'
  let cursor = getcurpos(a:window)[1:2]
  return {'target': a:window, 'current_window': current, 'previous_window': win_getid(winnr('#')),
        \ 'focus': focus, 'mode': mode(), 'tab': tabpagenr(), 'layout': winlayout(),
        \ 'cwd': s:Cwd(a:window), 'cursor': cursor, 'windows': windows, 'buffers': buffers,
        \ 'context': s:Read(a:window, v:null, max([1, cursor[0] - 8]), cursor[0] + 12)}
endfunction

function! s:LoadedBuffer(file) abort
  let target = resolve(a:file)
  for info in getbufinfo({'bufloaded': 1})
    if info.name !=# '' && resolve(info.name) ==# target
      return info.bufnr
    endif
  endfor
  return -1
endfunction

" Reads the live buffer for a file when one is loaded, otherwise the disk.
function! s:Read(window, file, first, last) abort
  let first = a:first is v:null ? 1 : a:first
  let buffer = a:file is v:null ? winbufnr(a:window) : s:LoadedBuffer(a:file)
  if buffer > 0
    call s:Refresh(buffer)
    let [file, total] = [s:Path(buffer), getbufinfo(buffer)[0].linecount]
    let modified = getbufvar(buffer, '&modified') ? v:true : v:false
  else
    call s:Require(getftype(resolve(a:file)) ==# 'file' && filereadable(a:file), 'File does not exist: ' . a:file)
    let content = readfile(a:file) + ['']
    let [file, total, modified] = [a:file, max([1, len(content) - 1]), v:false]
  endif
  let last = min([a:last is v:null ? first + 79 : a:last, total])
  call s:Require(first <= last, s:Outside(first, first, file, total))
  if buffer > 0
    let lines = getbufline(buffer, first, last)
  else
    let lines = map(content[first - 1 : last - 1], {_, line -> s:Utf8(line)})
  endif
  return {'file': file, 'start': first, 'end': last, 'lines': lines, 'modified': modified}
endfunction

" Reads text that is not valid UTF-8 as Latin-1, as Vim's default
" 'fileencodings' would.
function! s:Utf8(text) abort
  if a:text =~# '^[\x01-\x7f]*$' || iconv(iconv(a:text, 'utf-8', 'utf-32'), 'utf-32', 'utf-8') ==# a:text
    return a:text
  endif
  return iconv(a:text, 'latin1', 'utf-8')
endfunction

function! s:ValidateRange(buffer, first, last) abort
  let last = a:last is v:null ? a:first : a:last
  let total = getbufinfo(a:buffer)[0].linecount
  call s:Require(a:first <= last && last <= total, s:Outside(a:first, last, bufname(a:buffer), total))
  return last
endfunction

function! s:Outside(first, last, file, total) abort
  let lines = a:first == a:last ? 'Line ' . a:first . ' is' : printf('Lines %d-%d are', a:first, a:last)
  let name = a:file ==# '' ? 'the buffer' : fnamemodify(a:file, ':t')
  return printf('%s outside %s, which has %d line%s.', lines, name, a:total, a:total == 1 ? '' : 's')
endfunction

function! s:Load(file, allow_missing) abort
  call s:Require(index(['', 'file'], getftype(resolve(a:file))) >= 0, 'Not a regular file: ' . a:file)
  call s:Require(filereadable(a:file) || a:allow_missing || bufloaded(a:file), 'File does not exist: ' . a:file)
  let buffer = bufadd(a:file)
  if !bufloaded(buffer)
    " bufload() fails on a file that has another swap file and never asks
    " SwapExists, so skip the check. Such a file then gets a swap file other
    " than .swp, and opens read-only, as Vim's own prompt would offer.
    let shortmess = &shortmess
    set shortmess+=A
    try
      call bufload(buffer)
    finally
      let &shortmess = shortmess
    endtry
    if swapname(buffer) !=# '' && swapname(buffer) !~# '\.swp$'
      call setbufvar(buffer, '&readonly', 1)
    endif
  endif
  call s:Refresh(buffer)
  return buffer
endfunction

" Shows a buffer in the code window. Runs inside that window.
function! s:Switch(buffer) abort
  let previous_buffer = bufnr()
  let previous_bufhidden = getbufvar(previous_buffer, '&bufhidden')
  " bufhidden=hide prevents option-driven writes and destructive unloading as well.
  call setbufvar(previous_buffer, '&bufhidden', 'hide')
  try
    execute 'keepalt keepjumps hide buffer ' . a:buffer
  finally
    if bufexists(previous_buffer)
      call setbufvar(previous_buffer, '&bufhidden', previous_bufhidden)
    endif
  endtry
endfunction

function! s:Display(window, buffer) abort
  call win_execute(a:window, 'call ' . s:sid . 'Switch(' . a:buffer . ')')
endfunction

function! s:Show(window, file, first, last, note) abort
  let buffer = s:Load(a:file, 0)
  let annotate = a:first isnot v:null || a:last isnot v:null || a:note !=# ''
  let first = a:first is v:null ? 1 : a:first
  if annotate
    call s:ValidateRange(buffer, first, a:last)
  endif
  call s:Clear(a:window)
  call s:Display(a:window, buffer)
  return annotate ? s:Annotate(a:window, first, a:last, a:note) : {'file': s:Path(buffer)}
endfunction

function! s:Annotate(window, first, last, note) abort
  let buffer = winbufnr(a:window)
  let last = s:ValidateRange(buffer, a:first, a:last)
  let state = s:Session(a:window)
  call s:ClearMarks(state)
  let notes = a:note ==# '' ? [] : map(split(a:note, "\n", 1), '"  " . v:val')
  if has('nvim')
    let mark = {'end_row': last, 'end_col': 0, 'hl_group': 'TandemRange', 'hl_eol': v:true, 'priority': 150}
    if !empty(notes)
      let mark.virt_lines = map(copy(notes), '[[v:val, "TandemNote"]]')
      let mark.virt_lines_above = v:true
    endif
    call nvim_buf_set_extmark(buffer, state.namespace, a:first - 1, 0, mark)
  else
    call prop_add(a:first, 1, {'type': state.range_type, 'bufnr': buffer, 'end_lnum': last,
          \ 'end_col': strlen(getbufline(buffer, last)[0]) + 1})
    for line in reverse(copy(notes))
      call prop_add(a:first, 0, {'type': state.note_type, 'bufnr': buffer, 'text': line, 'text_align': 'above'})
    endfor
  endif
  let state.marked_buffer = buffer
  call win_execute(a:window, 'call cursor(' . a:first . ', 1) | normal! zvzz')
  if has('nvim') && a:first == 1 && !empty(notes)
    " Lines above the first line only show when the window scrolls up to them.
    call win_execute(a:window, 'call winrestview({"topline": 1, "topfill": ' . len(notes) . '})')
  endif
  return {'file': s:Path(buffer), 'start': a:first, 'end': last}
endfunction

function! s:Git(directory, args) abort
  let command = ['git', '-C', a:directory] + a:args
  if has('nvim')
    " Unlike system(), this keeps stderr out of the output and skips 'shell'.
    let [code, output] = luaeval('(function(r) return {r.code, r.stdout or ""} end)(vim.system(_A, {text = true}):wait())', command)
    return [code == 0, output]
  endif
  " system() runs 'shell', so use a plain one whatever the user's settings.
  let saved = [&shell, &shellcmdflag, &shellquote, &shellxquote, &shellredir]
  let [&shell, &shellcmdflag, &shellquote, &shellxquote, &shellredir] = ['/bin/sh', '-c', '', '', '>%s 2>&1']
  try
    let output = system(join(map(command, 'shellescape(v:val)')) . ' 2>/dev/null')
    return [v:shell_error == 0, output]
  finally
    let [&shell, &shellcmdflag, &shellquote, &shellxquote, &shellredir] = saved
  endtry
endfunction

" Returns the file at a Git revision: {revision, path, lines, tracked}.
function! s:GitVersion(file, base) abort
  let directory = fnamemodify(a:file, ':h')
  while !isdirectory(directory)
    let parent = fnamemodify(directory, ':h')
    call s:Require(parent !=# directory, 'File has no existing parent directory.')
    let directory = parent
  endwhile
  let [ok, root] = s:Git(directory, ['rev-parse', '--show-toplevel'])
  call s:Require(ok, 'File is not in a Git repository.')
  let root = resolve(trim(root))
  let [ok, revision] = s:Git(directory, ['rev-parse', '--verify', '--end-of-options', a:base . '^{commit}'])
  call s:Require(ok, 'Unknown Git revision: ' . a:base)
  let revision = trim(revision)
  let real = resolve(a:file)
  call s:Require(stridx(real, root . '/') == 0, 'File is outside the Git repository.')
  let path = strpart(real, strlen(root) + 1)
  let [tracked, content] = s:Git(root, ['show', revision . ':' . path])
  if !tracked
    " A file added after the revision compares against an empty baseline.
    let [ok, entry] = s:Git(root, ['ls-tree', '--name-only', revision, '--', path])
    call s:Require(ok && entry ==# '', 'Could not read the Git version of this file.')
    let content = ''
  endif
  let lines = split(substitute(content, "\r\n", "\n", 'g'), "\n", 1)
  if len(lines) > 1 && lines[-1] ==# ''
    call remove(lines, -1)
  endif
  return {'revision': revision, 'path': path, 'lines': lines, 'tracked': tracked}
endfunction

function! s:RequireNoOtherDiff(window) abort
  let own = get(s:Find(a:window), 'diff', {})
  let tab = win_id2tabwin(a:window)[0]
  for info in getwininfo()
    if info.tabnr == tab && gettabwinvar(info.tabnr, info.winnr, '&diff')
      call s:Require(!empty(own) && (info.winid == own.source || (info.winid == own.window && info.bufnr == own.buffer)),
            \ 'This tab already has a diff open. Close it before starting another comparison.')
    endif
  endfor
endfunction

function! s:Diff(window, file, base) abort
  let file = a:file is v:null ? s:Path(winbufnr(a:window)) : a:file
  call s:Require(file !=# '', 'The code buffer has no file name.')
  let committed = s:GitVersion(file, a:base)
  call s:RequireNoOtherDiff(a:window)
  let buffer = s:Load(file, committed.tracked)
  call s:Clear(a:window)
  call s:Display(a:window, buffer)
  call s:OpenBaseline(a:window, buffer, committed)
  return {'file': s:Path(buffer), 'base': committed.revision, 'baseline_window': s:Session(a:window).diff.window,
        \ 'working_window': a:window, 'modified': getbufvar(buffer, '&modified') ? v:true : v:false}
endfunction

function! s:OpenBaseline(window, buffer, committed) abort
  let baseline = bufadd(printf('tandem://%d/%s/%s', a:window, strpart(a:committed.revision, 0, 8), a:committed.path))
  call setbufvar(baseline, '&buftype', 'nofile')
  noautocmd call bufload(baseline)
  call setbufline(baseline, 1, a:committed.lines)
  call setbufvar(baseline, '&filetype', getbufvar(a:buffer, '&filetype'))
  call setbufvar(baseline, '&swapfile', 0)
  call setbufvar(baseline, '&bufhidden', 'wipe')
  call setbufvar(baseline, '&modified', 0)
  call setbufvar(baseline, '&modifiable', 0)
  call setbufvar(baseline, '&readonly', 1)
  let split = winwidth(a:window) >= s:side_by_side_width ? 'leftabove vsplit' : 'leftabove split'
  call win_execute(a:window, split . ' | call ' . s:sid . 'InstallBaseline(' . a:window . ', ' . baseline . ')')
  call win_execute(a:window, 'diffthis')
endfunction

" Runs inside the new comparison window.
function! s:InstallBaseline(source, buffer) abort
  call s:Switch(a:buffer)
  let state = s:Session(a:source)
  let state.diff = {'source': a:source, 'window': win_getid(), 'buffer': a:buffer}
  diffthis
endfunction
