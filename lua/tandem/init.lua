local M = {}

local options = { claude_cmd = true, codex_cmd = true, width = true }

--- Sets g:tandem_* options from Lua, e.g. require("tandem").setup({ width = 0.4 }).
function M.setup(opts)
  for key, value in pairs(opts or {}) do
    if options[key] then
      vim.g["tandem_" .. key] = value
    else
      vim.notify(("tandem: unknown option %q"):format(key), vim.log.levels.WARN)
    end
  end
end

return M
