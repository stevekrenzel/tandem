if exists('g:loaded_neovim_tour')
  finish
endif
let g:loaded_neovim_tour = 1

command! -nargs=* Codex call neovim_tour#Launch('codex', 'partner', <q-args>)
command! -nargs=* CodexTour call neovim_tour#Launch('codex', 'tour', <q-args>)
command! -nargs=* Claude call neovim_tour#Launch('claude', 'partner', <q-args>)
command! -nargs=* ClaudeTour call neovim_tour#Launch('claude', 'tour', <q-args>)
command! TourClear call neovim_tour#ClearAll()
