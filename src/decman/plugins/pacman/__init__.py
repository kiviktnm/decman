import shutil

import decman.core.module as module
import decman.core.store as _store
import decman.plugins as plugins

# Re-exports
from decman.plugins.pacman.commands import PacmanCommands
from decman.plugins.pacman.package import CustomPackage

__all__ = [
    "PacmanCommands",
    "CustomPackage",
    "packages",
    "aur_packages",
    "custom_packages",
    "Pacman",
]


def packages(fn):
    """
    Annotate that this function returns a set of pacman package names that should be installed.

    Return type of ``fn``: ``set[str]``
    """
    fn.__pacman__packages__ = True
    return fn


def aur_packages(fn):
    """
    Annotate that this function returns a set of AUR package names that should be installed.

    Return type of ``fn``: ``set[str]``
    """
    fn.__aur__packages__ = True
    return fn


def custom_packages(fn):
    """
    Annotate that this function returns a set of ``CustomPackage``s that should be installed.

    Return type of ``fn``: ``set[CustomPackage]``
    """
    fn.__custom__packages__ = True
    return fn


class Pacman(plugins.Plugin):
    """
    Plugin that manages pacman packages added directly to ``packages`` or declared by modules via
    @packages.
    """

    NAME = "pacman"

    def __init__(self) -> None:
        self.packages: set[str] = set()
        self.aur_packages: set[str] = set()
        self.commands = PacmanCommands()

    def available(self) -> bool:
        return shutil.which("pacman") is not None

    def process_modules(self, store: _store.Store, modules: set[module.Module]):
        # This is used to track changes in modules.
        store.ensure("packages_for_module", {})

    def apply(
        self, store: _store.Store, dry_run: bool = False, params: list[str] | None = None
    ) -> bool:
        return True
