"""
Module containing the CLI Application.
"""

import os
import sys

from decman.lib import AUR, Pacman, Systemd, Store, print_error


def main():
    """
    Main entry for the CLI app
    """

    aur = AUR()

    print(aur.get_package_info("zapzap"))

    if not is_root():
        print_error("Not running as root. Please run decman as root.")
        sys.exit(1)

    p = Pacman()

    print(p.get_versioned_foreign_packages())


def is_root() -> bool:
    """
    Returns True if the process is running as root.
    """

    return os.geteuid() == 0


if __name__ == "__main__":
    main()
