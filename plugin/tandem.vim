if exists('g:loaded_tandem')
  finish
endif
let g:loaded_tandem = 1

command! -nargs=* Codex call tandem#Launch('codex', 'partner', <q-args>)
command! -nargs=* CodexTour call tandem#Launch('codex', 'tour', <q-args>)
command! -nargs=* Claude call tandem#Launch('claude', 'partner', <q-args>)
command! -nargs=* ClaudeTour call tandem#Launch('claude', 'tour', <q-args>)
command! TandemClear call tandem#ClearAll()
