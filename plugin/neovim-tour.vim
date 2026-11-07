if has('nvim') || exists('g:loaded_neovim_tour_vim')
  finish
endif
let g:loaded_neovim_tour_vim = 1

command! -nargs=* Codex call neovim_tour#Launch(<q-args>)
command! TourClear call neovim_tour#ClearAll()
