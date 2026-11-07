local M = {}
local api = vim.api
local root = vim.fn.fnamemodify(vim.uv.fs_realpath(debug.getinfo(1, "S").source:sub(2)), ":h:h:h")
local options = { codex_cmd = { "codex", "--no-daemon" }, width = 0.42 }
local sessions = {}

local function highlights()
  api.nvim_set_hl(0, "NeovimTourRange", { default = true, link = "Visual" })
  api.nvim_set_hl(0, "NeovimTourNote", { default = true, link = "DiagnosticInfo" })
end
highlights()
api.nvim_create_autocmd("ColorScheme", { callback = highlights })

function M.setup(config)
  options = vim.tbl_deep_extend("force", options, config or {})
end

-- Avoid users' BufLeave autosaves and terminal WinEnter/startinsert mappings while
-- temporarily visiting the code pane. Keep file-loading and syntax events enabled.
local function quiet_navigation(fn)
  local previous = vim.o.eventignore
  if previous ~= "all" then
    local ignored = previous == "" and {} or vim.split(previous, ",")
    vim.list_extend(ignored, { "BufLeave", "BufWinLeave", "BufEnter", "BufWinEnter", "WinLeave", "WinEnter", "FocusLost" })
    vim.o.eventignore = table.concat(ignored, ",")
  end
  local ok, result = pcall(fn)
  vim.o.eventignore = previous
  if not ok then
    error(result, 0)
  end
  return result
end

local function target(window)
  assert(type(window) == "number" and api.nvim_win_is_valid(window), "Code window was closed. Start :Codex from a code window again.")
  assert(vim.bo[api.nvim_win_get_buf(window)].buftype == "", "The target must be a code window, not a terminal or special buffer.")
  return window
end

local function session(window)
  if not sessions[window] then
    sessions[window] = { namespace = api.nvim_create_namespace("neovim-tour:" .. window) }
  end
  return sessions[window]
end

local function clear_marks(state)
  if state.marked_buffer and api.nvim_buf_is_valid(state.marked_buffer) then
    api.nvim_buf_clear_namespace(state.marked_buffer, state.namespace, 0, -1)
  end
  state.marked_buffer = nil
end

local function clear_diff(state)
  local diff = state.diff
  if not diff then
    return
  end
  if api.nvim_win_is_valid(diff.source) then
    api.nvim_win_call(diff.source, function() vim.cmd("diffoff") end)
  end
  if api.nvim_win_is_valid(diff.window) and api.nvim_win_get_buf(diff.window) == diff.buffer then
    api.nvim_win_close(diff.window, true)
  end
  if api.nvim_buf_is_valid(diff.buffer) then
    api.nvim_buf_delete(diff.buffer, { force = true })
  end
  state.diff = nil
end

local function clear(window)
  local state = sessions[window]
  if state then
    clear_marks(state)
    clear_diff(state)
  end
  return { cleared = true }
end

function M.clear_all()
  quiet_navigation(function()
    for window in pairs(sessions) do
      clear(window)
    end
  end)
end

local function buffer_info(buffer)
  return {
    id = buffer, file = api.nvim_buf_get_name(buffer),
    modified = vim.bo[buffer].modified, buftype = vim.bo[buffer].buftype,
    lines = api.nvim_buf_line_count(buffer),
  }
end

local function read(window, first, last)
  local buffer = api.nvim_win_get_buf(window)
  local count = api.nvim_buf_line_count(buffer)
  first = first or 1
  last = math.min(last or (first + 79), count)
  assert(first >= 1 and first <= count and last >= first, "Line range is outside the buffer.")
  return { file = api.nvim_buf_get_name(buffer), start = first, finish = last,
    lines = api.nvim_buf_get_lines(buffer, first - 1, last, false) }
end

local function inspect(window)
  local windows, buffers = {}, {}
  for _, win in ipairs(api.nvim_list_wins()) do
    windows[#windows + 1] = { id = win, buffer = api.nvim_win_get_buf(win),
      cursor = api.nvim_win_get_cursor(win), tab = api.nvim_win_get_tabpage(win) }
  end
  for _, buffer in ipairs(api.nvim_list_bufs()) do
    if api.nvim_buf_is_loaded(buffer) then
      buffers[#buffers + 1] = buffer_info(buffer)
    end
  end
  local cursor = api.nvim_win_get_cursor(window)
  return { target = window, current_window = api.nvim_get_current_win(),
    cwd = vim.fn.getcwd(), windows = windows, buffers = buffers,
    cursor = cursor, context = read(window, math.max(1, cursor[1] - 8), cursor[1] + 12) }
end

local function validate_range(buffer, first, last)
  local count = api.nvim_buf_line_count(buffer)
  last = last or first
  assert(first >= 1 and last >= first and last <= count, "Line range is outside the buffer.")
  return last
end

local function annotate(window, first, last, note)
  local buffer = api.nvim_win_get_buf(window)
  last = validate_range(buffer, first, last)
  local state = session(window)
  clear_marks(state)
  local mark = { end_row = last, end_col = 0, hl_group = "NeovimTourRange", hl_eol = true, priority = 150 }
  if note and note ~= "" then
    mark.virt_lines = {}
    for _, line in ipairs(vim.split(note, "\n", { plain = true })) do
      mark.virt_lines[#mark.virt_lines + 1] = { { "  " .. line, "NeovimTourNote" } }
    end
    mark.virt_lines_above = true
  end
  api.nvim_buf_set_extmark(buffer, state.namespace, first - 1, 0, mark)
  state.marked_buffer = buffer
  api.nvim_win_call(window, function()
    api.nvim_win_set_cursor(window, { first, 0 })
    vim.cmd("normal! zvzz")
  end)
  return { file = api.nvim_buf_get_name(buffer), start = first, finish = last }
end

local function load_file(file, allow_missing)
  assert(type(file) == "string" and file ~= "", "A file path is required.")
  local stat = vim.uv.fs_stat(file)
  assert(not stat or stat.type == "file", "Path is not a regular file.")
  local buffer = vim.fn.bufadd(file)
  assert(stat or allow_missing or api.nvim_buf_is_loaded(buffer), "File does not exist: " .. file)
  vim.fn.bufload(buffer)
  return buffer
end

local function switch_buffer(window, buffer)
  local previous_buffer = api.nvim_win_get_buf(window)
  local previous_bufhidden = vim.bo[previous_buffer].bufhidden
  -- Neovim can autowrite or unload a buffer independently of navigation events.
  vim.bo[previous_buffer].bufhidden = "hide"
  local ok, err = pcall(api.nvim_win_set_buf, window, buffer)
  if api.nvim_buf_is_valid(previous_buffer) then
    vim.bo[previous_buffer].bufhidden = previous_bufhidden
  end
  if not ok then error(err, 0) end
  return buffer
end

local function git(directory, args)
  local command = { "git", "-C", directory }
  vim.list_extend(command, args)
  local output = vim.fn.system(command)
  return vim.v.shell_error == 0, output
end

local function show_diff(window, file, base)
  local current = api.nvim_win_get_buf(window)
  file = file or api.nvim_buf_get_name(current)
  assert(file ~= "", "The code buffer has no file name.")
  local directory = vim.fn.fnamemodify(file, ":h")
  while vim.fn.isdirectory(directory) == 0 do
    local parent = vim.fn.fnamemodify(directory, ":h")
    assert(parent ~= directory, "File has no existing parent directory.")
    directory = parent
  end
  local ok, repository = git(directory, { "rev-parse", "--show-toplevel" })
  assert(ok, "File is not in a Git repository.")
  repository = vim.trim(repository)
  local valid, revision = git(directory, { "rev-parse", "--verify", "--end-of-options", (base or "HEAD") .. "^{commit}" })
  assert(valid, "Unknown Git revision: " .. (base or "HEAD"))
  revision = vim.trim(revision)
  local real_file = vim.uv.fs_realpath(file) or file
  local real_root = vim.uv.fs_realpath(repository) or repository
  assert(real_file:sub(1, #real_root + 1) == real_root .. "/", "File is outside the Git repository.")
  local relative = real_file:sub(#real_root + 2)
  local exists, content = git(repository, { "show", revision .. ":" .. relative })
  if not exists then
    local listed, entry = git(repository, { "ls-tree", "--name-only", revision, "--", relative })
    assert(listed and entry == "", "Could not read the Git version of this file.")
    content = ""
  end
  local state = session(window)
  for _, win in ipairs(api.nvim_tabpage_list_wins(api.nvim_win_get_tabpage(window))) do
    local own_diff = state.diff
    local is_tour_window = own_diff and (win == own_diff.source
      or (win == own_diff.window and api.nvim_win_get_buf(win) == own_diff.buffer))
    assert(not vim.wo[win].diff or is_tour_window,
      "This tab already contains an unrelated diff. Close that comparison before starting a tour diff.")
  end
  local buffer = load_file(file, exists)
  clear(window)
  switch_buffer(window, buffer)
  local baseline = api.nvim_create_buf(false, true)
  local lines = vim.split(content:gsub("\r\n", "\n"), "\n", { plain = true })
  if lines[#lines] == "" and #lines > 1 then table.remove(lines) end
  api.nvim_buf_set_lines(baseline, 0, -1, false, lines)
  vim.bo[baseline].filetype = vim.bo[buffer].filetype
  vim.bo[baseline].bufhidden = "wipe"
  vim.bo[baseline].modifiable = false
  api.nvim_buf_set_name(baseline, "neovim-tour://" .. window .. "/" .. revision:sub(1, 8) .. "/" .. relative)
  api.nvim_win_call(window, function()
    vim.cmd("leftabove vsplit")
    local base_window = api.nvim_get_current_win()
    api.nvim_win_set_buf(base_window, baseline)
    state.diff = { source = window, window = base_window, buffer = baseline }
    vim.cmd("diffthis")
  end)
  api.nvim_win_call(window, function() vim.cmd("diffthis") end)
  return { file = file, base = revision, baseline_window = state.diff.window,
    working_window = window, modified = vim.bo[buffer].modified }
end

function M.request(args)
  local ok, result = pcall(function()
    return quiet_navigation(function()
      local window = target(args.window)
      if args.action == "state" then
        return inspect(window)
      elseif args.action == "read" then
        return read(window, args.start, args["end"])
      elseif args.action == "show" then
        local buffer = load_file(args.file, false)
        validate_range(buffer, args.line, args["end"])
        clear(window)
        switch_buffer(window, buffer)
        return annotate(window, args.line, args["end"], args.note)
      elseif args.action == "highlight" then
        return annotate(window, args.start, args["end"], args.note)
      elseif args.action == "diff" then
        return show_diff(window, args.file, args.base)
      elseif args.action == "clear" then
        return clear(window)
      end
      error("Unknown tour action: " .. tostring(args.action))
    end)
  end)
  if not ok then
    return { ok = false, error = tostring(result) }
  end
  return { ok = true, result = result }
end

function M.launch(prompt)
  local window = target(api.nvim_get_current_win())
  assert(vim.fn.executable(options.codex_cmd[1]) == 1, "Codex executable was not found on PATH.")
  local helper = root .. "/skills/neovim-tour/scripts/nvim-tour"
  local cwd = vim.fn.getcwd()
  local command = vim.deepcopy(options.codex_cmd)
  command[#command + 1] = "Use $neovim-tour. " .. ((prompt and prompt ~= "") and prompt
    or "Connect to this Neovim session, inspect the code pane, and ask what I want to explore.")
  quiet_navigation(function()
    vim.cmd("botright vsplit")
    vim.cmd("enew")
    local available = api.nvim_win_get_width(window) + api.nvim_win_get_width(0)
    api.nvim_win_set_width(0, math.max(20, math.floor(available * options.width)))
    local job = vim.fn.jobstart(command, {
      term = true, cwd = cwd,
      env = { NEOVIM_TOUR_EDITOR = "neovim", NEOVIM_TOUR_SERVER = vim.v.servername,
        NEOVIM_TOUR_SOCKET = vim.v.servername, NEOVIM_TOUR_WINDOW = tostring(window),
        NEOVIM_TOUR_CLI = helper, NEOVIM_TOUR_NVIM = vim.v.progpath },
    })
    assert(job > 0, "Could not start Codex. Check the configured codex_cmd.")
  end)
  vim.cmd("startinsert")
end

return M
