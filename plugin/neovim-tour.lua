if vim.g.loaded_neovim_tour then
  return
end
vim.g.loaded_neovim_tour = true

vim.api.nvim_create_user_command("Codex", function(opts)
  require("neovim_tour").launch(opts.args)
end, { nargs = "*", desc = "Start Codex connected to this code window" })

vim.api.nvim_create_user_command("TourClear", function()
  require("neovim_tour").clear_all()
end, { desc = "Clear tour annotations and tour diff panes" })
