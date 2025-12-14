import os
import shutil

import decman.config as config
import decman.core.error as errors
import decman.core.module as module
import decman.core.output as output
import decman.core.store as _store
import decman.plugins as plugins
from decman.plugins.aur.commands import AurCommands, AurPacmanInterface
from decman.plugins.aur.error import (
    AurRPCError,
    DependencyCycleError,
    ForeignPackageManagerError,
    PKGBUILDParseError,
)
from decman.plugins.aur.fpm import ForeignPackageManager
from decman.plugins.aur.package import CustomPackage, PackageSearch

# Re-exports
__all__ = [
    "AUR",
    "AurCommands",
    "CustomPackage",
    "packages",
    "custom_packages",
]


def packages(fn):
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


class AUR(plugins.Plugin):
    """
    Plugin that manages additional pacman packages installed outside the pacman repos.

    AUR packages are added directly to ``packages`` or declared by modules via ``@aur.packages``.

    Custom packages are added directly to ``custom_packages`` or declared by modules via
    ``@aur.custom_packages``.
    """

    NAME = "aur"

    def __init__(self) -> None:
        self.packages: set[str] = set()
        self.custom_packages: set[CustomPackage] = set()
        self.ignored_packages: set[str] = set()
        self.commands: AurCommands = AurCommands()

        self.aur_rpc_timeout: int = 30
        self.print_highlights: bool = True
        self.keywords: set[str] = {
            "pacsave",
            "pacnew",
            # These cause too many false positives IMO
            # "warning",
            # "error",
            # "note",
        }
        self.build_dir: str = "/tmp/decman/build"
        self.makepkg_user: str = "nobody"

    def available(self) -> bool:
        return (
            shutil.which("pacman") is not None
            and shutil.which("git") is not None
            and shutil.which("mkarchroot") is not None
        )

    def process_modules(self, store: _store.Store, modules: set[module.Module]):
        # This is used to track changes in modules.
        store.ensure("aur_packages_for_module", {})
        store.ensure("custom_packages_for_module", {})

        for mod in modules:
            store["aur_packages_for_module"].setdefault(mod.name, set())
            store["custom_packages_for_module"].setdefault(mod.name, set())

            aur_packages = plugins.run_method_with_attribute(mod, "__aur__packages__") or set()
            custom_packages = (
                plugins.run_method_with_attribute(mod, "__custom__packages__") or set()
            )

            if store["aur_packages_for_module"][mod.name] != aur_packages:
                mod._changed = True

            if store["custom_packages_for_module"][mod.name] != custom_packages:
                mod._changed = True

            self.packages |= aur_packages
            self.custom_packages |= custom_packages

            store["aur_packages_for_module"][mod.name] = aur_packages
            store["custom_packages_for_module"][mod.name] = custom_packages

    def apply(
        self, store: _store.Store, dry_run: bool = False, params: list[str] | None = None
    ) -> bool:
        params = params or []
        upgrade_devel = "aur-upgrade-devel" in params
        force = "aur-force" in params
        pkg_cache_dir = os.path.join(config.cache_dir, "aur/")

        if not dry_run:
            try:
                os.makedirs(pkg_cache_dir, exist_ok=True)
            except OSError as error:
                output.print_error("Failed to ensure AUR package cache directory exists.")
                output.print_continuation(f"{error.strerror or error}")
                output.print_traceback()

                return False

        try:
            package_search = PackageSearch(self.aur_rpc_timeout)
            for custom_package in self.custom_packages:
                package_search.add_custom_pkg(custom_package.parse(self.commands))
            pm = AurPacmanInterface(self.commands, self.print_highlights, self.keywords)
            fpm = ForeignPackageManager(
                store,
                pm,
                package_search,
                self.commands,
                pkg_cache_dir,
                self.build_dir,
                self.makepkg_user,
            )

            custom_package_names = {p.pkgname for p in self.custom_packages}
            currently_installed_native = pm.get_native_explicit()
            currently_installed_foreign = pm.get_foreign_explicit()
            orphans = pm.get_foreign_orphans()

            to_remove = (
                (currently_installed_foreign | orphans)
                - self.packages
                - custom_package_names
                - self.ignored_packages
            )

            actually_to_remove = set()
            to_set_as_dependencies = set()

            dependants_to_keep = (
                self.packages
                | custom_package_names
                | currently_installed_native
                # don't remove ignored packages' dependencies
                | (self.ignored_packages & currently_installed_foreign)
            )
            for package in to_remove:
                dependants = pm.get_dependants(package)
                if any(dependant in dependants_to_keep for dependant in dependants):
                    to_set_as_dependencies.add(package)
                else:
                    actually_to_remove.add(package)

            if actually_to_remove:
                output.print_list("Removing foreign packages:", sorted(actually_to_remove))
                if not dry_run:
                    pm.remove(actually_to_remove)

            if to_set_as_dependencies:
                output.print_list(
                    "Setting previously explicitly installed foreign packages as dependencies:",
                    sorted(to_set_as_dependencies),
                )
                if not dry_run:
                    pm.set_as_dependencies(to_set_as_dependencies)

            output.print_summary("Upgrading foreign packages.")
            if not dry_run:
                fpm.upgrade(upgrade_devel, force, self.ignored_packages)

            to_install = (
                (self.packages | custom_package_names)
                - currently_installed_foreign
                - self.ignored_packages
            )
            output.print_list("Installing foreign packages:", sorted(to_install))

            if not dry_run:
                fpm.install(list(to_install), force=force)
        except AurRPCError as error:
            output.print_error("Failed to fetch data from AUR RPC.")
            output.print_continuation(f"{error}")
            output.print_traceback()
            return False
        except DependencyCycleError as error:
            output.print_error("Foreign package dependency cycle detected.")
            output.print_continuation(f"{error}")
            output.print_traceback()
            return False
        except PKGBUILDParseError as error:
            output.print_error("Failed to parse a CustomPackage PKGBUILD.")
            output.print_continuation(f"{error}")
            output.print_traceback()
            return False
        except ForeignPackageManagerError as error:
            output.print_error("Foreign package manager failed.")
            output.print_continuation(f"{error}")
            output.print_traceback()
            return False
        except errors.CommandFailedError as error:
            output.print_error("Running a command failed.")
            output.print_continuation(f"{error}")
            output.print_traceback()
            return False

        return True
