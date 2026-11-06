#!/usr/bin/env python3
"""Install or uninstall Neovim Tour with symlinks; leave existing configuration alone."""

import argparse
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    parser.add_argument("--nvim-data-dir", type=Path,
                        default=data_home / os.environ.get("NVIM_APPNAME", "nvim"))
    parser.add_argument("--skill-dir", type=Path, default=Path.home() / ".agents/skills")
    parser.add_argument("--bin-dir", type=Path, default=Path.home() / ".local/bin")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()
    links = [
        (args.nvim_data_dir / "site/pack/neovim-tour/start/neovim-tour", ROOT),
        (args.skill_dir / "neovim-tour", ROOT / "skills/neovim-tour"),
        (args.bin_dir / "nvim-tour", ROOT / "skills/neovim-tour/scripts/nvim-tour"),
    ]
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
        print("Open Neovim, then run :Codex from a code window.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
