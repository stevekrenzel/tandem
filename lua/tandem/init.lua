local M = {}

function M.setup(opts)
  for key, value in pairs(opts or {}) do
    vim.g["tandem_" .. key] = value
  end
end

return M
