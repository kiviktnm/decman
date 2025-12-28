import decman.plugins.pacman as pacman

import decman.config as config
import decman.core.command as command


class AurCommands(pacman.PacmanCommands):
    def install_as_dependencies(self, pkgs: set[str]) -> list[str]:
        """
        Running this command installs the given packages from pacman repositories.
        The packages are installed as dependencies.
        """
        return ["pacman", "-S", "--needed", "--asdeps"] + list(pkgs)

    def install_files_as_dependencies(self, pkg_files: list[str]) -> list[str]:
        """
        Running this command installs the given packages files as dependencies.
        """
        return ["pacman", "-U", "--asdeps"] + pkg_files

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

    def make_chroot(self, chroot_dir: str, with_pkgs: set[str]) -> list[str]:
        """
        Running this command creates a new arch chroot to the chroot directory and installs the
        given packages there.
        """
        return ["mkarchroot", chroot_dir] + list(with_pkgs)

    def install_chroot(self, chroot_dir: str, packages: list[str]):
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

    def resolve_real_name_chroot(self, chroot_dir: str, pkg: str) -> list[str]:
        """
        This command prints a real name of a package.
        For example, it prints the package which provides a virtual package.
        """
        return [
            "arch-nspawn",
            chroot_dir,
            "pacman",
            "-Sddp",
            "--print-format=%n",
            pkg,
        ]

    def remove_chroot(self, chroot_dir: str, packages: set[str]):
        """
        Running this command removes the given packages from the given chroot.
        """
        return ["arch-nspawn", chroot_dir, "pacman", "-Rsu", "--noconfirm"] + list(packages)

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

    def print_srcinfo(self) -> list[str]:
        """
        Running this command prints SRCINFO generated from the package in the current
        working directory.
        """
        return ["makepkg", "--printsrcinfo"]


class AurPacmanInterface(pacman.PacmanInterface):
    """
    High level interface for running pacman commands.

    On failure methods raise a ``CommandFailedError``.
    """

    def __init__(
        self,
        commands: AurCommands,
        print_highlights: bool,
        keywords: set[str],
        dbsiglevel: int,
        dbpath: str,
    ) -> None:
        super().__init__(commands, print_highlights, keywords, dbsiglevel, dbpath)
        self._installable: dict[str, bool] = {}
        self._aur_commands = commands

    def get_foreign_orphans(self) -> set[str]:
        """
        Returns a set of orphaned foreign packages.
        """
        return self._get_orphans(pacman.PacmanInterface._is_foreign)

    def is_installable(self, pkg: str) -> bool:
        """
        Returns True if a package can be installed using pacman.
        """
        return (
            pacman.strip_dependency(pkg) in self._name_index
            or pacman.strip_dependency(pkg) in self._provides_index
        )

    def get_versioned_foreign_packages(self) -> list[tuple[str, str]]:
        """
        Returns a list of installed packages and their versions that aren't from pacman databases,
        basically AUR packages.
        """
        out: list[tuple[str, str]] = []
        for pkg in self._handle.get_localdb().pkgcache:
            if not self._is_native(pkg.name):
                out.append((pkg.name, pkg.version))
        return out

    def install_dependencies(self, deps: set[str]):
        """
        Installs the given dependencies.
        """
        if not deps:
            return

        cmd = self._aur_commands.install_as_dependencies(deps)
        pacman_output = command.prg(cmd)
        self.print_highlighted_pacman_messages(pacman_output)

    def install_files(self, files: list[str], as_explicit: set[str]):
        """
        Installs the given files first as dependencies. Then the packages listed in as_explicit are
        installed explicitly.
        """
        if not files:
            return

        cmd = self._aur_commands.install_files_as_dependencies(files)
        pacman_output = command.prg(cmd)
        self.print_highlighted_pacman_messages(pacman_output)

        if not as_explicit:
            return

        cmd = self._commands.set_as_explicit(as_explicit)
        command.prg(cmd, pty=config.debug_output)
