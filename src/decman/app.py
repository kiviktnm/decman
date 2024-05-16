"""
Module containing the CLI Application.
"""

import argparse
import os
import sys
import traceback

import decman
import decman.error as err
import decman.lib as l
import decman.config as conf
from decman.lib import fpm


def main():
    """
    Main entry for the CLI app
    """

    parser = argparse.ArgumentParser(
        prog="decman",
        description=
        "Declarative package & configuration manager for Arch Linux",
        epilog="See more help at: https://github.com/kiviktnm/decman")

    parser.add_argument("--source",
                        action="store",
                        help="python file containing configuration")
    parser.add_argument(
        "--print",
        action="store_true",
        default=False,
        help=
        "print what would happen as a result of running decman (doesn't print removed files)"
    )
    parser.add_argument(
        "--no-packages",
        action="store_true",
        default=False,
        help="don't upgrade any packages (including foreign packages)")
    parser.add_argument("--no-foreign-packages",
                        action="store_true",
                        default=False,
                        help="don't upgrade foreign packages")
    parser.add_argument("--no-files",
                        action="store_true",
                        default=False,
                        help="don't install any files")
    parser.add_argument("--no-systemd-units",
                        action="store_true",
                        default=False,
                        help="don't enable/disable systemd units")
    parser.add_argument("--no-commands",
                        action="store_true",
                        default=False,
                        help="don't run user specified commands")
    parser.add_argument("--upgrade-devel",
                        action="store_true",
                        default=False,
                        help="upgrade devel packages")
    parser.add_argument(
        "--force-build",
        action="store_true",
        default=False,
        help="force building of packages that are already cached")

    args = parser.parse_args()

    if not _is_root():
        l.print_error("Not running as root. Please run decman as root.")
        sys.exit(1)

    original_wd = os.getcwd()

    try:
        store = l.Store.restore()
        opts = _set_up(store, args)
        Core(store, opts).run()
    except err.UserFacingError as error:
        l.print_error(error.user_facing_msg)
        for line in traceback.format_exc().splitlines():
            l.print_debug(line)
        sys.exit(1)
    except decman.UserRaisedError as user_error:
        l.print_error(
            f"Error encountered while running the source: {user_error}")
        sys.exit(1)

    # Save even when an error has occurred, since this avoids repeating steps like building pkgs.
    try:
        store.save()
    except err.UserFacingError as error:
        l.print_error(error.user_facing_msg)
        for line in traceback.format_exc().splitlines():
            l.print_debug(line)
        sys.exit(1)

    os.chdir(original_wd)


def _set_up(store: l.Store, args):
    source = store.source_file
    source_changed = False
    if args.source is not None:
        source = args.source
        source_changed = True

    if source is None:
        l.print_error(
            "Source was not specified. Please specify a source with the '--source' argument."
        )
        l.print_info("Decman will remember the previously specified source.")
        sys.exit(1)

    if source_changed or not store.allow_running_source_without_prompt:
        l.print_warning(f"Decman will run the file '{source}' as root!")
        l.print_warning(
            "Only proceed if you trust the file completely. The file can also import other files."
        )

        if not l.prompt_confirm("Proceed?", default=False):
            sys.exit(1)

        if l.prompt_confirm("Remember this choice?", default=False):
            store.allow_running_source_without_prompt = True

    source_path = os.path.abspath(source)
    source_dir = os.path.dirname(source_path)
    store.source_file = source_path

    try:
        with open(source_path, "rt", encoding="utf-8") as file:
            content = file.read()
    except OSError as e:
        raise err.UserFacingError(
            f"Failed to read source file '{store.source_file}'.") from e

    os.chdir(source_dir)
    sys.path.append(".")
    exec(content)

    return args.print, not args.no_packages, not args.no_foreign_packages, not args.no_files, not args.no_systemd_units, not args.no_commands, args.upgrade_devel, args.force_build


class Core:
    """
    Contains the main logic of decman.
    """

    def __init__(self, store: l.Store, opts):
        self.only_print, self.update_packages, self.update_foreign_packages, self.update_files, self.update_units, self.run_commands, self.upgrade_devel, self.force_build = opts

        self.store = store
        self.source = _resolve_source()
        self.pacman = l.Pacman()
        self.systemctl = l.Systemd(store)
        self.fpkg_search = fpm.ExtendedPackageSearch(self.pacman)

        for upkg in self.source.all_user_pkgs():
            self.fpkg_search.add_user_pkg(
                fpm.PackageInfo.from_user_package(upkg, self.pacman))

        self.fpm = fpm.ForeignPackageManager(store, self.pacman,
                                             self.fpkg_search)

    def run(self):
        """
        Run the main logic of decman.
        """
        if self.update_units:
            self._disable_units()

        if self.update_files:
            self._create_and_remove_files()

        if self.update_packages:
            self._remove_pkgs()
            self._upgrade_pkgs()
            self._install_pkgs()

        if self.update_units:
            self._enable_units()

        if self.run_commands:
            self._run_modules()
            all_enabled_modules = {}
            for mod, version in self.source.all_enabled_modules():
                all_enabled_modules[mod] = version
            # Enabled modules are really only stored for commands,
            # so they can be set only when the commands were exacuted.
            self.store.enabled_modules = all_enabled_modules

    def _disable_units(self):
        to_disable = self.source.units_to_disable(self.store)
        l.print_list_summary("Disabling systemd units:", to_disable)
        if not self.only_print:
            self.systemctl.disable_units(to_disable)

        user_units_to_disable = self.source.user_units_to_disable(self.store)
        for user, units in user_units_to_disable.items():
            l.print_list_summary(f"Disabling systemd units for {user}:", units)
            if not self.only_print:
                self.systemctl.disable_user_units(units, user)

    def _remove_pkgs(self):
        currently_installed = self.pacman.get_installed()
        to_remove = self.source.packages_to_remove(currently_installed)
        l.print_list_summary("Removing packages:", to_remove)
        if not self.only_print:
            self.pacman.remove(to_remove)

    def _upgrade_pkgs(self):
        l.print_summary("Upgrading packages.")
        if not self.only_print:
            self.pacman.upgrade()
            if conf.enable_fpm and self.update_foreign_packages:
                self.fpm.upgrade(self.upgrade_devel, self.force_build,
                                 self.source.ignored_packages)

    def _install_pkgs(self):
        currently_installed = self.pacman.get_installed()
        to_install_pacman = self.source.pacman_packages_to_install(
            currently_installed)
        to_install_fpm = self.source.foreign_packages_to_install(
            currently_installed)

        l.print_list_summary("Installing pacman packages:", to_install_pacman)

        # fpm prints a summary so no need to print it twice
        if self.only_print:
            l.print_list_summary("Installing foreign packages:",
                                 to_install_fpm)

        if not self.only_print:
            self.pacman.install(to_install_pacman)
            if conf.enable_fpm and self.update_foreign_packages:
                self.fpm.install(to_install_fpm, force=self.force_build)

    def _create_and_remove_files(self):
        l.print_list_summary("Installing files:",
                             self.source.all_file_targets(),
                             elements_per_line=1)
        l.print_list_summary("Installing directories:",
                             self.source.all_directory_targets(),
                             elements_per_line=1)

        if self.only_print:
            return

        all_created = self.source.create_all_files()
        to_remove = self.source.files_to_remove(self.store, all_created)

        l.print_list_summary("Removing files:", to_remove, elements_per_line=1)

        for file in to_remove:
            try:
                os.remove(file)
            except OSError as e:
                l.print_error(f"{e}")
                l.print_warning(f"Failed to remove file: {file}")

        self.store.created_files = all_created

    def _enable_units(self):
        to_enable = self.source.units_to_enable(self.store)
        l.print_list_summary("Enabling systemd units:", to_enable)
        if not self.only_print:
            self.systemctl.enable_units(to_enable)

        user_units_to_enable = self.source.user_units_to_enable(self.store)
        for user, units in user_units_to_enable.items():
            l.print_list_summary(f"Enabling systemd units for {user}:", units)
            if not self.only_print:
                self.systemctl.enable_user_units(units, user)

    def _run_modules(self):
        l.print_summary("Running on enable hooks.")
        if not self.only_print:
            self.source.run_on_enable(self.store)

        l.print_summary("Running after version change hooks.")
        if not self.only_print:
            self.source.run_after_version_change(self.store)

        l.print_summary("Running on disable hooks.")
        if not self.only_print:
            self.source.run_on_disable(self.store)

        l.print_summary("Running after update hooks.")
        if not self.only_print:
            self.source.run_after_update()


def _resolve_source() -> l.Source:
    enabled_systemd_user_units = {}
    for user, units in decman.enabled_systemd_user_units.items():
        enabled_systemd_user_units[user] = set(units)

    return l.Source(
        pacman_packages=set(decman.packages),
        aur_packages=set(decman.aur_packages),
        user_packages=set(decman.user_packages),
        ignored_packages=set(decman.ignored_packages),
        systemd_units=set(decman.enabled_systemd_units),
        systemd_user_units=enabled_systemd_user_units,
        files=decman.files,
        directories=decman.directories,
        modules=set(decman.modules),
    )


def _is_root() -> bool:
    return os.geteuid() == 0
