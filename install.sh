#!/bin/bash
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
editor=neovim
nvim_data=${XDG_DATA_HOME:-$HOME/.local/share}/${NVIM_APPNAME:-nvim}
vim_dir=$HOME/.vim
uninstall=false

usage() {
  cat <<'USAGE'
Usage: ./install.sh [--editor neovim|vim|macvim|both] [--uninstall]
                    [--nvim-data-dir DIR] [--vim-dir DIR]

Link this checkout into the editor's native package directory (default: Neovim).
Plugin manager users do not need this script.
USAGE
}

while (($#)); do
  case $1 in
    --editor|--nvim-data-dir|--vim-dir)
      (($# >= 2)) || { usage >&2; exit 1; }
      case $1 in
        --editor) editor=$2 ;;
        --nvim-data-dir) nvim_data=$2 ;;
        --vim-dir) vim_dir=$2 ;;
      esac
      shift 2 ;;
    --uninstall) uninstall=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 1 ;;
  esac
done

destinations=()
case $editor in
  neovim|both) destinations+=("$nvim_data/site/pack/neovim-tour/start/neovim-tour") ;;
  vim|macvim) ;;
  *) usage >&2; exit 1 ;;
esac
case $editor in
  vim|macvim|both) destinations+=("$vim_dir/pack/neovim-tour/start/neovim-tour") ;;
esac

for destination in "${destinations[@]}"; do
  if [[ -e $destination || -L $destination ]]; then
    if [[ ! -L $destination || $(readlink "$destination") != "$root" ]]; then
      printf '%s already exists and is not this installation; leaving it untouched.\n' "$destination" >&2
      exit 1
    fi
  fi
done
for destination in "${destinations[@]}"; do
  if $uninstall; then
    if [[ -L $destination ]]; then rm -- "$destination"; fi
  elif [[ ! -L $destination ]]; then
    mkdir -p -- "$(dirname -- "$destination")"
    ln -s -- "$root" "$destination"
  fi
  printf '%s\n' "$destination"
done
if ! $uninstall; then printf 'Open your editor, then run :Codex or :Claude from a code window.\n'; fi
