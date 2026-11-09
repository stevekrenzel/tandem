if exists('g:loaded_tandem')
  finish
endif
let g:loaded_tandem = 1

command! -bang -range -nargs=* Claude
      \ call tandem#Launch('claude', 'partner', <q-args>, <bang>0, <range> ? [<line1>, <line2>] : [])
command! -bang -range -nargs=* ClaudeTour
      \ call tandem#Launch('claude', 'tour', <q-args>, <bang>0, <range> ? [<line1>, <line2>] : [])
command! -bang -range -nargs=* Codex
      \ call tandem#Launch('codex', 'partner', <q-args>, <bang>0, <range> ? [<line1>, <line2>] : [])
command! -bang -range -nargs=* CodexTour
      \ call tandem#Launch('codex', 'tour', <q-args>, <bang>0, <range> ? [<line1>, <line2>] : [])
command! TandemClear call tandem#ClearAll()
