if exists('g:loaded_neovim_tour')
  finish
endif
let g:loaded_neovim_tour = 1

command! -nargs=* Codex call neovim_tour#Launch(<q-args>)
command! TourClear call neovim_tour#ClearAll()
