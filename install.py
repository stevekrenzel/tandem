#!/usr/bin/env python3
"""Install Neovim Tour for Neovim, MacVim, or both without editing configuration."""

import argparse
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--editor", choices=("neovim", "macvim", "both"), default="neovim")
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    parser.add_argument("--nvim-data-dir", type=Path,
                        default=data_home / os.environ.get("NVIM_APPNAME", "nvim"))
    parser.add_argument("--skill-dir", type=Path, default=Path.home() / ".agents/skills")
    parser.add_argument("--vim-dir", type=Path, default=Path.home() / ".vim")
    parser.add_argument("--bin-dir", type=Path, default=Path.home() / ".local/bin")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()
    package_paths = {
        "neovim": args.nvim_data_dir / "site/pack/neovim-tour/start/neovim-tour",
        "macvim": args.vim_dir / "pack/neovim-tour/start/neovim-tour",
    }
    selected = tuple(package_paths) if args.editor == "both" else (args.editor,)
    links = [(package_paths[editor], ROOT) for editor in selected]
    shared_links = [
        (args.skill_dir / "neovim-tour", ROOT / "skills/neovim-tour"),
        (args.bin_dir / "nvim-tour", ROOT / "skills/neovim-tour/scripts/nvim-tour"),
    ]
    other_installed = any(editor not in selected and path.is_symlink() and path.resolve() == ROOT
                          for editor, path in package_paths.items())
    if not args.uninstall or not other_installed:
        links += shared_links
    for destination, source in links:
        if (destination.exists() or destination.is_symlink()) and not (
            destination.is_symlink() and destination.resolve() == source
        ):
            raise ValueError("%s already exists and is not this installation; leaving it untouched." % destination)
    for destination, source in links:
        if args.uninstall:
            if destination.is_symlink():
                destination.unlink()
                print("Removed %s" % destination)
        elif not destination.is_symlink():
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(source, target_is_directory=source.is_dir())
            print("Linked %s -> %s" % (destination, source))
        else:
            print("Already installed: %s" % destination)
    if not args.uninstall:
        print("Open your editor, then run :Codex from a code window.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
