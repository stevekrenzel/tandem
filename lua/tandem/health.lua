local M = {}

local agents = {
  { name = "Claude Code", option = "claude_cmd", default = { "claude" } },
  { name = "Codex", option = "codex_cmd", default = { "codex", "--no-daemon" } },
}

local function command(agent)
  local value = vim.g["tandem_" .. agent.option] or agent.default
  if type(value) == "string" then
    value = vim.split(value, "%s+", { trimempty = true })
  end
  return value
end

local function codex_allows_helper()
  local home = vim.env.CODEX_HOME or vim.fs.joinpath(vim.env.HOME, ".codex")
  for _, file in ipairs(vim.fn.glob(vim.fs.joinpath(home, "rules", "*.rules"), true, true)) do
    for _, line in ipairs(vim.fn.readfile(file)) do
      if line:match('^%s*prefix_rule%(pattern%s*=%s*%[%s*"tandem"%s*%]') and line:match('decision%s*=%s*"allow"') then
        return true
      end
    end
  end
  return false
end

function M.check()
  vim.health.start("Tandem")
  if vim.fn.has("nvim-0.11") == 1 then
    vim.health.ok("Neovim " .. tostring(vim.version()))
  else
    vim.health.error("Neovim 0.11 or newer is required")
  end
  for _, tool in ipairs({ "bash", "git" }) do
    if vim.fn.executable(tool) == 1 then
      vim.health.ok(tool .. " found")
    else
      vim.health.error(tool .. " not found", tool == "git" and "Git is needed for comparisons" or nil)
    end
  end

  local found = {}
  for _, agent in ipairs(agents) do
    local cmd = command(agent)
    if type(cmd) ~= "table" or type(cmd[1]) ~= "string" then
      vim.health.error(("g:tandem_%s must be a command such as %s"):format(agent.option, vim.inspect(agent.default)))
    elseif vim.fn.executable(cmd[1]) == 1 then
      found[agent.option] = true
      vim.health.ok(("%s: %s"):format(agent.name, vim.fn.exepath(cmd[1])))
    else
      vim.health.info(("%s: %s not found (set g:tandem_%s if it is installed elsewhere)"):format(agent.name, cmd[1], agent.option))
    end
  end
  if vim.tbl_isempty(found) then
    vim.health.error("Neither Claude Code nor Codex was found", "Install one of them and sign in")
  end

  if found.codex_cmd then
    if codex_allows_helper() then
      vim.health.ok("Codex may run the tandem helper outside its sandbox")
    else
      vim.health.info(
        "If Codex runs sandboxed, approve its first `tandem` command with \"don't ask again\", or add this line to ~/.codex/rules/default.rules:\n"
          .. 'prefix_rule(pattern=["tandem"], decision="allow")'
      )
    end
  end
end

return M
