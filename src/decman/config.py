"""
Module for decman configuration options.

NOTE: Do NOT use from imports as global variables might not work as you expect.

Only use:

import decman.config

or

import decman.config as whatever

-- Configuring commands --

Commands are stored as methods in the Commands-class.
The global variable 'commands' of this module is an instance of the Commands-class.

To change the defalts, create a new child class of the Commands-class and set the 'commands'
variable to an instance of your class. Look in the example directory for an example.
"""

import typing


class Commands:
    """
    Default commands.
    """

    def list_pkgs(self) -> list[str]:
        """
        Running this command outputs a newline seperated list of explicitly installed packages.
        """
        return ["pacman", "-Qeq", "--color=never"]

    def list_flatpak_pkgs(self) -> list[str]:
        """
        Running this command outputs a newline separated list of installed flatpak application ids
        The first line just says 'Application ID' so this one is ignored.
        """
        return ["flatpak", "list", "--app", "--columns", "application"]

    def list_foreign_pkgs_versioned(self) -> list[str]:
        """
        Running this command outputs a newline seperated list of installed packages and their
        versions that are not from pacman repositories.
        """
        return ["pacman", "-Qm", "--color=never"]

    def install_pkgs(self, pkgs: list[str]) -> list[str]:
        """
        Running this command installs the given packages from pacman repositories.
        """
        return ["pacman", "-S", "--color=always", "--needed"] + pkgs

    def install_flatpak_pkgs(self, pkgs: list[str]) -> list[str]:
        """
        Running this command installs all listed packages, and their dependencies/runtimes automatically.
        """
        return ["flatpak", "install"] + pkgs

    def install_files(self, pkg_files: list[str]) -> list[str]:
        """
        Running this command installs the given packages files.
        """
        return ["pacman", "-U", "--color=always", "--asdeps"] + pkg_files

    def set_as_explicitly_installed(self, pkgs: list[str]) -> list[str]:
        """
        Running this command installs sets the given as explicitly installed.
        """
        return ["pacman", "-D", "--color=always", "--asexplicit"] + pkgs

    def install_deps(self, deps: list[str]) -> list[str]:
        """
        Running this command installs the given packages from pacman repositories.
        The packages are installed as dependencies.
        """
        return ["pacman", "-S", "--color=always", "--needed", "--asdeps"] + deps

    def is_installable(self, pkg: str) -> list[str]:
        """
        This command exits with code 0 when a package is installable from pacman repositories.
        """
        return ["pacman", "-Sddp", pkg]

    def upgrade(self) -> list[str]:
        """
        Running this command upgrades all pacman packages.
        """
        return ["pacman", "-Syu", "--color=always"]

    def upgrade_flatpak(self) -> list[str]:
        """
        Updates all installed flatpak REFs including runtimes and dependencies.
        """
        return ["flatpak", "update"]

    def remove(self, pkgs: list[str]) -> list[str]:
        """
        Running this command removes the given packages and their dependencies
        (that aren't required by other packages).
        """
        return ["pacman", "-Rs", "--color=always"] + pkgs

    def remove_flatpak(self, pkgs: list[str]) -> list[str]:
        """
        Running this command will remove the listed REFs. Unused dependencies might be kept, but to remove them another command needs to be run.
        """
        return ["flatpak", "remove"] + pkgs

    def remove_unused_flatpak(self) -> list[str]:
        """
        This will remove all unused flatpak dependencies and runtimes.
        """
        return ["flatpak", "remove", "--unused"]

    def enable_units(self, units: list[str]) -> list[str]:
        """
        Running this command enables the given systemd units.
        """
        return ["systemctl", "enable"] + units

    def disable_units(self, units: list[str]) -> list[str]:
        """
        Running this command disables the given systemd units.
        """
        return ["systemctl", "disable"] + units

    def enable_user_units(self, units: list[str], user: str) -> list[str]:
        """
        Running this command enables the given systemd units for the user.
        """
        return ["systemctl", "--user", "-M", f"{user}@", "enable"] + units

    def disable_user_units(self, units: list[str], user: str) -> list[str]:
        """
        Running this command disables the given systemd units for the user.
        """
        return ["systemctl", "--user", "-M", f"{user}@", "disable"] + units

    def compare_versions(self, installed_version: str, new_version: str) -> list[str]:
        """
        Running this command outputs -1 when the installed version is older than the new version.
        """
        return ["vercmp", installed_version, new_version]

    def git_clone(self, repo: str, dest: str) -> list[str]:
        """
        Running this command clones a git repository to the the given destination.
        """
        return ["git", "clone", repo, dest]

    def git_diff(self, from_commit: str) -> list[str]:
        """
        Running this command outputs the difference between the given commit and
        the current state of the repository.
        """
        return ["git", "diff", from_commit]

    def git_get_commit_id(self) -> list[str]:
        """
        Running this command outputs the current commit id.
        """
        return ["git", "rev-parse", "HEAD"]

    def git_log_commit_ids(self) -> list[str]:
        """
        Running this command outputs commit hashes of the repository.
        """
        return ["git", "log", "--format=format:%H"]

    def review_file(self, file: str) -> list[str]:
        """
        Running this command outputs a file for the user to see.
        """
        return ["less", file]

    def make_chroot(self, chroot_dir: str, with_pkgs: list[str]) -> list[str]:
        """
        Running this command creates a new arch chroot to the chroot directory and installs the
        given packages there.
        """
        return ["mkarchroot", chroot_dir] + with_pkgs

    def install_chroot_packages(self, chroot_dir: str, packages: list[str]):
        """
        Running this command installs the given packages to the given chroot.
        """
        return [
            "arch-nspawn",
            chroot_dir,
            "pacman",
            "-S",
            "--needed",
            "--noconfirm",
        ] + packages

    def resolve_real_name(self, chroot_dir: str, pkg: str) -> list[str]:
        """
        This command prints a real name of a package. For example, it prints the package which provides a virtual package.
        """
        return [
            "arch-nspawn",
            chroot_dir,
            "pacman",
            "-Sddp",
            "--print-format=%n",
            pkg,
        ]

    def remove_chroot_packages(self, chroot_dir: str, packages: list[str]):
        """
        Running this command removes the given packages from the given chroot.
        """
        return ["arch-nspawn", chroot_dir, "pacman", "-Rsu", "--noconfirm"] + packages

    def make_chroot_pkg(
        self, chroot_wd_dir: str, user: str, pkgfiles_to_install: list[str]
    ) -> list[str]:
        """
        Running this command creates a package file using the given chroot.
        The package is created as the user and the pkg_files_to_install are installed
        in the chroot before the package is created.
        """
        makechrootpkg_cmd = ["makechrootpkg", "-c", "-r", chroot_wd_dir, "-U", user]

        for pkgfile in pkgfiles_to_install:
            makechrootpkg_cmd += ["-I", pkgfile]

        return makechrootpkg_cmd


commands: Commands = Commands()
debug_output: bool = False
quiet_output: bool = False
suppress_command_output: bool = True

valid_pkgexts: list[str] = [
    ".pkg.tar",
    ".pkg.tar.gz",
    ".pkg.tar.bz2",
    ".pkg.tar.xz",
    ".pkg.tar.zst",
    ".pkg.tar.lzo",
    ".pkg.tar.lrz",
    ".pkg.tar.lz4",
    ".pkg.tar.lz",
    ".pkg.tar.Z",
]

pacman_output_keywords: list[str] = [
    "pacsave",
    "pacnew",
    # These cause too many false positives IMO
    # "warning",
    # "error",
    # "note",
]
print_pacman_output_highlights: bool = True

makepkg_user: str = "nobody"
build_dir: str = "/tmp/decman/build"
pkg_cache_dir: str = "/var/cache/decman"
aur_rpc_timeout: typing.Optional[int] = 30
enable_fpm: bool = True
enable_flatpak: bool = False
number_of_packages_stored_in_cache: int = 3
