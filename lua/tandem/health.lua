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

local codex_rule = 'prefix_rule(pattern=["tandem"], decision="allow")'

-- Whether the user's Codex rules let a command run outside the sandbox without
-- asking. Asks Codex itself, so any form of rule counts. nil if Codex can't say.
local function codex_allows(codex, words)
  local home = vim.env.CODEX_HOME or vim.fs.joinpath(vim.env.HOME, ".codex")
  local argv = { codex, "execpolicy", "check" }
  for _, file in ipairs(vim.fn.glob(vim.fs.joinpath(home, "rules", "*.rules"), true, true)) do
    vim.list_extend(argv, { "--rules", file })
  end
  if #argv == 3 then
    return false
  end
  vim.list_extend(argv, { "--" })
  vim.list_extend(argv, words)
  local ok, result = pcall(function()
    return vim.system(argv, { text = true }):wait(10000)
  end)
  if not ok or result.code ~= 0 then
    return nil
  end
  local decoded, answer = pcall(vim.json.decode, result.stdout)
  return decoded and type(answer) == "table" and answer.decision == "allow"
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
    local allowed = codex_allows(command(agents[2])[1], { "tandem", "ex", "vsplit" })
    local file = vim.fn["tandem#CodexRulesFile"]()
    if allowed == nil then
      vim.health.info("Could not check your Codex rules with `codex execpolicy`")
    elseif allowed then
      vim.health.ok("Codex may run tandem commands without asking")
    elseif vim.g.tandem_codex_rules == 0 or vim.g.tandem_codex_rules == false then
      vim.health.info(
        "Codex asks before it runs tandem commands. To let it run them without asking, add this line to "
          .. vim.fn.fnamemodify(file, ":h")
          .. "/default.rules:\n"
          .. codex_rule
      )
    elseif vim.fn.filereadable(file) == 1 then
      vim.health.warn("Codex asks before it runs tandem commands, despite " .. file,
        "The file may have been edited, or another rule may require approval")
    else
      vim.health.info("Codex asks before it runs tandem commands until you first run :Codex, which writes " .. file)
    end
  end
end

return M
