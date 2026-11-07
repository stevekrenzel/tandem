let s:root = fnamemodify(resolve(expand('<sfile>:p')), ':h:h')
let s:prefix = expand('<SID>')
let s:sessions = {}

function! s:Highlights() abort
  highlight default link NeovimTourRange Visual
  highlight default link NeovimTourNote Special
endfunction
call s:Highlights()
augroup neovim_tour
  autocmd!
  autocmd ColorScheme * call s:Highlights()
augroup END

function! s:Require(condition, message) abort
  if !a:condition
    throw a:message
  endif
endfunction

function! s:IgnoreNavigation() abort
  let previous = &eventignore
  if previous !=# 'all'
    let events = ['BufLeave', 'BufWinLeave', 'BufEnter', 'BufWinEnter', 'WinLeave', 'WinEnter', 'FocusLost']
    let &eventignore = join(filter(split(previous, ',') + events, 'v:val !=# ""'), ',')
  endif
  return previous
endfunction

function! s:Target(window) abort
  call s:Require(type(a:window) == v:t_number && win_id2tabwin(a:window) !=# [0, 0],
        \ 'Code window was closed. Start :Codex from a code window again.')
  let buffer = winbufnr(a:window)
  call s:Require(getbufvar(buffer, '&buftype') ==# '', 'The target must be a code window, not a terminal or special buffer.')
  return a:window
endfunction

function! s:Session(window) abort
  let key = string(a:window)
  if !has_key(s:sessions, key)
    if has('nvim')
      let state = {'namespace': nvim_create_namespace('neovim-tour:' . key)}
    else
      let state = {'range_type': 'NeovimTourRange_' . key, 'note_type': 'NeovimTourNote_' . key}
      call prop_type_add(state.range_type, {'highlight': 'NeovimTourRange', 'priority': 150, 'combine': 1})
      call prop_type_add(state.note_type, {'highlight': 'NeovimTourNote', 'priority': 150})
    endif
    let s:sessions[key] = state
  endif
  return s:sessions[key]
endfunction

function! s:ClearMarks(state) abort
  if !has_key(a:state, 'marked_buffer')
    return
  endif
  if bufloaded(a:state.marked_buffer)
    if has('nvim')
      call nvim_buf_clear_namespace(a:state.marked_buffer, a:state.namespace, 0, -1)
    else
      call prop_remove({'types': [a:state.range_type, a:state.note_type], 'bufnr': a:state.marked_buffer, 'all': 1})
    endif
  endif
  unlet a:state.marked_buffer
endfunction

function! s:Clear(window) abort
  let state = get(s:sessions, string(a:window), {})
  if empty(state)
    return {'cleared': v:true}
  endif
  call s:ClearMarks(state)
  if has_key(state, 'diff')
    let diff = state.diff
    if win_id2tabwin(diff.source) !=# [0, 0]
      call win_execute(diff.source, 'diffoff')
    endif
    if win_id2tabwin(diff.window) !=# [0, 0] && winbufnr(diff.window) == diff.buffer
      call win_execute(diff.window, 'close!')
    endif
    if bufexists(diff.buffer)
      execute 'bwipeout! ' . diff.buffer
    endif
    unlet state.diff
  endif
  return {'cleared': v:true}
endfunction

function! neovim_tour#ClearAll() abort
  let previous = s:IgnoreNavigation()
  try
    for window in keys(s:sessions)
      call s:Clear(str2nr(window))
    endfor
  finally
    let &eventignore = previous
  endtry
endfunction

function! s:Read(window, first, last) abort
  let buffer = winbufnr(a:window)
  let line_count = getbufinfo(buffer)[0].linecount
  let last = min([a:last is v:null ? a:first + 79 : a:last, line_count])
  call s:Require(a:first >= 1 && a:first <= line_count && last >= a:first, 'Line range is outside the buffer.')
  return {'file': bufname(buffer), 'start': a:first, 'finish': last, 'lines': getbufline(buffer, a:first, last)}
endfunction

function! s:Inspect(window) abort
  let windows = []
  for win in getwininfo()
    let position = getcurpos(win.winid)
    call add(windows, {'id': win.winid, 'buffer': win.bufnr, 'cursor': [position[1], position[2] - 1], 'tab': win.tabnr})
  endfor
  let buffers = []
  for buffer in getbufinfo({'bufloaded': 1})
    call add(buffers, {'id': buffer.bufnr, 'file': buffer.name, 'lines': buffer.linecount,
          \ 'modified': buffer.changed ? v:true : v:false, 'buftype': getbufvar(buffer.bufnr, '&buftype')})
  endfor
  let position = getcurpos(a:window)
  return {'target': a:window, 'current_window': win_getid(), 'cwd': getcwd(), 'windows': windows,
        \ 'buffers': buffers, 'cursor': [position[1], position[2] - 1],
        \ 'context': s:Read(a:window, max([1, position[1] - 8]), position[1] + 12)}
endfunction

function! s:ValidateRange(buffer, first, last) abort
  let last = a:last is v:null ? a:first : a:last
  call s:Require(a:first >= 1 && last >= a:first && last <= getbufinfo(a:buffer)[0].linecount,
        \ 'Line range is outside the buffer.')
  return last
endfunction

function! s:Annotate(window, first, last, note) abort
  let buffer = winbufnr(a:window)
  let last = s:ValidateRange(buffer, a:first, a:last)
  let state = s:Session(a:window)
  call s:ClearMarks(state)
  if has('nvim')
    let mark = {'end_row': last, 'end_col': 0, 'hl_group': 'NeovimTourRange', 'hl_eol': v:true, 'priority': 150}
    if a:note !=# ''
      let mark.virt_lines = map(split(a:note, "\n", 1), '[["  " . v:val, "NeovimTourNote"]]')
      let mark.virt_lines_above = v:true
    endif
    call nvim_buf_set_extmark(buffer, state.namespace, a:first - 1, 0, mark)
  else
    call prop_add(a:first, 1, {'type': state.range_type, 'bufnr': buffer, 'end_lnum': last,
          \ 'end_col': strlen(getbufline(buffer, last)[0]) + 1})
    for line in reverse(split(a:note, "\n", 1))
      if line !=# ''
        call prop_add(a:first, 0, {'type': state.note_type, 'bufnr': buffer, 'text': '  ' . line, 'text_align': 'above'})
      endif
    endfor
  endif
  let state.marked_buffer = buffer
  call win_execute(a:window, 'call cursor(' . a:first . ',1) | normal! zvzz')
  return {'file': bufname(buffer), 'start': a:first, 'finish': last}
endfunction

function! s:Load(file, allow_missing) abort
  call s:Require(type(a:file) == v:t_string && a:file !=# '', 'A file path is required.')
  call s:Require(index(['', 'file'], getftype(resolve(a:file))) >= 0, 'Path is not a regular file.')
  let buffer = bufadd(a:file)
  call s:Require(filereadable(a:file) || a:allow_missing || bufloaded(buffer), 'File does not exist: ' . a:file)
  call bufload(buffer)
  return buffer
endfunction

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

function! s:Git(directory, args) abort
  let command = ['git', '-C', a:directory] + a:args
  let invocation = has('nvim') ? command : join(map(command, 'shellescape(v:val)'), ' ')
  let output = system(invocation)
  return [v:shell_error == 0, output]
endfunction

function! s:InstallBaseline(source, buffer) abort
  call s:Switch(a:buffer)
  let s:sessions[string(a:source)].diff = {'source': a:source, 'window': win_getid(), 'buffer': a:buffer}
  diffthis
endfunction

function! s:Diff(window, file, base) abort
  let file = a:file is v:null ? getbufinfo(winbufnr(a:window))[0].name : a:file
  call s:Require(file !=# '', 'The code buffer has no file name.')
  let directory = fnamemodify(file, ':h')
  while !isdirectory(directory)
    let parent = fnamemodify(directory, ':h')
    call s:Require(parent !=# directory, 'File has no existing parent directory.')
    let directory = parent
  endwhile
  let [ok, repository] = s:Git(directory, ['rev-parse', '--show-toplevel'])
  call s:Require(ok, 'File is not in a Git repository.')
  let repository = trim(repository)
  let [valid, revision] = s:Git(directory, ['rev-parse', '--verify', '--end-of-options', a:base . '^{commit}'])
  call s:Require(valid, 'Unknown Git revision: ' . a:base)
  let revision = trim(revision)
  let real_file = resolve(file)
  let real_root = resolve(repository)
  call s:Require(stridx(real_file, real_root . '/') == 0, 'File is outside the Git repository.')
  let relative = strpart(real_file, strlen(real_root) + 1)
  let [exists, content] = s:Git(repository, ['show', revision . ':' . relative])
  if !exists
    let [listed, entry] = s:Git(repository, ['ls-tree', '--name-only', revision, '--', relative])
    call s:Require(listed && entry ==# '', 'Could not read the Git version of this file.')
    let content = ''
  endif
  let state = s:Session(a:window)
  let tab = win_id2tabwin(a:window)[0]
  for win in getwininfo()
    if win.tabnr == tab && gettabwinvar(win.tabnr, win.winid, '&diff')
      let own = get(state, 'diff', {})
      let is_tour_window = !empty(own) && (win.winid == own.source || (win.winid == own.window && win.bufnr == own.buffer))
      call s:Require(is_tour_window, 'This tab already contains an unrelated diff. Close that comparison before starting a tour diff.')
    endif
  endfor
  let buffer = s:Load(file, exists)
  call s:Clear(a:window)
  call win_execute(a:window, 'call ' . s:prefix . 'Switch(' . buffer . ')')
  let baseline = bufadd('neovim-tour://' . a:window . '/' . strpart(revision, 0, 8) . '/' . relative)
  call setbufvar(baseline, '&buftype', 'nofile')
  noautocmd call bufload(baseline)
  let lines = split(substitute(content, "\r\n", "\n", 'g'), "\n", 1)
  if len(lines) > 1 && lines[-1] ==# ''
    call remove(lines, -1)
  endif
  call setbufline(baseline, 1, lines)
  call setbufvar(baseline, '&filetype', getbufvar(buffer, '&filetype'))
  call setbufvar(baseline, '&swapfile', 0)
  call setbufvar(baseline, '&bufhidden', 'wipe')
  call setbufvar(baseline, '&modified', 0)
  call setbufvar(baseline, '&modifiable', 0)
  call setbufvar(baseline, '&readonly', 1)
  call win_execute(a:window, 'leftabove vsplit | call ' . s:prefix . 'InstallBaseline(' . a:window . ',' . baseline . ')')
  call win_execute(a:window, 'diffthis')
  return {'file': file, 'base': revision, 'baseline_window': state.diff.window,
        \ 'working_window': a:window, 'modified': getbufvar(buffer, '&modified') ? v:true : v:false}
endfunction

function! neovim_tour#Request(args) abort
  let previous = s:IgnoreNavigation()
  try
    let window = s:Target(a:args.window)
    let action = a:args.action
    if action ==# 'state'
      let result = s:Inspect(window)
    elseif action ==# 'read'
      let result = s:Read(window, a:args.start, a:args.end)
    elseif action ==# 'show'
      let buffer = s:Load(a:args.file, 0)
      call s:ValidateRange(buffer, a:args.line, a:args.end)
      call s:Clear(window)
      call win_execute(window, 'call ' . s:prefix . 'Switch(' . buffer . ')')
      let result = s:Annotate(window, a:args.line, a:args.end, a:args.note)
    elseif action ==# 'highlight'
      let result = s:Annotate(window, a:args.start, a:args.end, a:args.note)
    elseif action ==# 'diff'
      let result = s:Diff(window, a:args.file, a:args.base)
    elseif action ==# 'clear'
      let result = s:Clear(window)
    else
      throw 'Unknown tour action: ' . action
    endif
    return {'ok': v:true, 'result': result}
  catch
    return {'ok': v:false, 'error': v:exception}
  finally
    let &eventignore = previous
  endtry
endfunction

function! neovim_tour#Command(argv, cwd, window) abort
  try
    let argv = copy(a:argv)
    let action = remove(argv, 0)
    let options = {
          \ 'state': [], 'read': ['start', 'end'], 'show': ['line', 'end', 'note'],
          \ 'highlight': ['end', 'note'], 'diff': ['base'], 'clear': []}
    call s:Require(has_key(options, action), 'Unknown tour command: ' . action)
    let args = {'action': action, 'window': str2nr(a:window), 'start': 1, 'line': 1,
          \ 'end': v:null, 'note': '', 'file': v:null, 'base': 'HEAD'}
    let positional = []
    let literal = 0
    while !empty(argv)
      let argument = remove(argv, 0)
      if argument ==# '--' && !literal
        let literal = 1
      elseif stridx(argument, '--') == 0 && !literal
        let name = matchstr(argument, '^--\zs[^=]*')
        call s:Require(index(options[action], name) >= 0, 'Unknown option: ' . argument)
        if stridx(argument, '=') >= 0
          let args[name] = strpart(argument, stridx(argument, '=') + 1)
        else
          call s:Require(!empty(argv), 'Missing value for ' . argument)
          let args[name] = remove(argv, 0)
        endif
      else
        call add(positional, argument)
      endif
    endwhile
    if action ==# 'show' || action ==# 'highlight'
      call s:Require(len(positional) == 1, action . ' requires one argument.')
      let args[action ==# 'show' ? 'file' : 'start'] = positional[0]
    elseif action ==# 'diff'
      call s:Require(len(positional) <= 1, 'diff accepts at most one file.')
      let args.file = get(positional, 0, v:null)
    else
      call s:Require(empty(positional), 'Unexpected argument for ' . action)
    endif
    for name in ['start', 'line', 'end']
      if args[name] isnot v:null
        let value = type(args[name]) == v:t_number ? string(args[name]) : args[name]
        call s:Require(value =~# '^[0-9]\+$' && str2nr(value) > 0,
              \ name . ' must be a positive integer.')
        let args[name] = str2nr(args[name])
      endif
    endfor
    if args.file isnot v:null
      let file = args.file =~# '^\~/' ? expand('~') . strpart(args.file, 1) : args.file
      let args.file = resolve(simplify(file =~# '^/' ? file : a:cwd . '/' . file))
    endif
    let response = neovim_tour#Request(args)
  catch
    let response = {'ok': v:false, 'error': v:exception}
  endtry
  return (response.ok ? '0' : '1') . "\n" . json_encode(response)
endfunction

function! neovim_tour#Launch(prompt) abort
  call s:Require(has('nvim') || (has('clientserver') && has('terminal') && has('textprop')),
        \ 'Vim requires +clientserver, +terminal, and +textprop features.')
  let window = s:Target(win_getid())
  let command = copy(get(g:, 'neovim_tour_codex_cmd', ['codex', '--no-daemon']))
  call s:Require(!empty(command) && executable(command[0]), 'Codex executable was not found on PATH.')
  if has('nvim') && v:servername ==# ''
    call serverstart()
  elseif v:servername ==# ''
    call remote_startserver('NEOVIM_TOUR_' . getpid())
  endif
  call s:Require(v:servername !=# '', 'No MacVim server. Open the MacVim GUI before starting :Codex.')
  call add(command, 'Read and follow ' . s:root . '/skills/neovim-tour/SKILL.md. ' . (a:prompt ==# ''
        \ ? 'Connect to this editor session, inspect the code pane, and ask what I want to explore.' : a:prompt))
  let previous = s:IgnoreNavigation()
  try
    let cwd = getcwd()
    botright vsplit
    enew
    execute 'vertical resize ' . max([20, float2nr(&columns * get(g:, 'neovim_tour_width', 0.42))])
    let env = {'NEOVIM_TOUR_EDITOR': has('nvim') ? 'neovim' : 'macvim', 'NEOVIM_TOUR_SERVER': v:servername,
          \ 'NEOVIM_TOUR_WINDOW': string(window), 'NEOVIM_TOUR_CLI': s:root . '/skills/neovim-tour/scripts/nvim-tour'}
    if has('nvim')
      let env.NEOVIM_TOUR_SOCKET = v:servername
      let env.NEOVIM_TOUR_NVIM = v:progpath
      let terminal = jobstart(command, {'term': v:true, 'cwd': cwd, 'env': env})
    else
      let env.NEOVIM_TOUR_VIM = resolve(exepath(v:progpath))
      let backend = index(v:argv, '--clientserver')
      if backend >= 0
        let env.VIM_CLIENTSERVER = v:argv[backend + 1]
      endif
      let terminal = term_start(command, {'curwin': 1, 'cwd': cwd, 'env': env})
    endif
    call s:Require(terminal > 0, 'Could not start Codex. Check g:neovim_tour_codex_cmd.')
  finally
    let &eventignore = previous
  endtry
  startinsert
endfunction
