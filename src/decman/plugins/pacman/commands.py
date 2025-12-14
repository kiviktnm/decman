import decman.core.command as command
import decman.core.error as errors
import decman.core.output as output


class PacmanCommands:
    def list_explicit(self) -> list[str]:
        """
        Running this command outputs a newline seperated list of explicitly installed native
        packages.
        """
        return ["pacman", "-Qeq", "--color=never"]

    def list_orphans(self) -> list[str]:
        """
        Running this command outputs a newline seperated list of orphaned packages.
        """
        return ["pacman", "-Qdtq", "--color=never"]

    def list_dependants(self, pkg: str) -> list[str]:
        """
        Running this command outputs a newline seperated list of packages that depend on the given
        package.
        """
        return ["pacman", "-Rc", "--print", "--print-format", "%n", pkg]

    def list_foreign_versioned(self) -> list[str]:
        """
        Running this command outputs a newline seperated list of installed packages and their
        versions that are not from pacman repositories.
        """
        return ["pacman", "-Qm", "--color=never"]

    def is_installable(self, pkg: str) -> list[str]:
        """
        This command exits with code 0 when a package is installable from pacman repositories.
        """
        return ["pacman", "-Sddp", pkg]

    def install(self, pkgs: set[str]) -> list[str]:
        """
        Running this command installs the given packages from pacman repositories.
        """
        return ["pacman", "-S", "--needed"] + list(pkgs)

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

    def upgrade(self) -> list[str]:
        """
        Running this command upgrades all pacman packages.
        """
        return ["pacman", "-Syu"]

    def set_as_dependencies(self, pkgs: set[str]) -> list[str]:
        """
        Running this command installs sets the given packages as dependencies.
        """
        return ["pacman", "-D", "--asdeps"] + list(pkgs)

    def set_as_explicit(self, pkgs: set[str]) -> list[str]:
        """
        Running this command installs sets the given as explicitly installed.
        """
        return ["pacman", "-D", "--asexplicit"] + list(pkgs)

    def remove(self, pkgs: set[str]) -> list[str]:
        """
        Running this command removes the given packages and their dependencies
        (that aren't required by other packages).
        """
        return ["pacman", "-Rs"] + list(pkgs)

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


class PacmanInterface:
    """
    High level interface for running pacman commands.

    On failure methods raise a ``CommandFailedError``.
    """

    def __init__(
        self, commands: PacmanCommands, print_highlights: bool, keywords: set[str]
    ) -> None:
        self._installable: dict[str, bool] = {}
        self._commands = commands
        self._print_highlights = print_highlights
        self._keywords = keywords

    def get_installed(self) -> list[str]:
        """
        Returns a list of installed packages.
        """

        returncode, packages_text = command.run(self._commands.list_explicit())
        packages = packages_text.strip().split("\n")

        if returncode != 0:
            raise errors.CommandFailedError(self._commands.list_explicit(), packages_text)

        return packages

    def is_installable(self, pkg: str) -> bool:
        """
        Returns True if a package can be installed using pacman.
        """
        if pkg in self._installable:
            return self._installable[pkg]

        returncode, _ = command.run(self._commands.is_installable(pkg))
        result = returncode == 0

        self._installable[pkg] = result
        return result

    def get_versioned_foreign_packages(self) -> list[tuple[str, str]]:
        """
        Returns a list of installed packages and their versions that aren't from pacman databases,
        basically AUR packages.
        """
        cmd = self._commands.list_foreign_versioned()
        returncode, packages_text = command.run(cmd)
        packages = [
            (line.split(" ")[0], line.split(" ")[1]) for line in packages_text.strip().split("\n")
        ]

        if returncode != 0:
            raise errors.CommandFailedError(cmd, packages_text)

        return packages

    def install(self, packages: set[str]):
        """
        Installs the given packages. If the packages are already installed, marks them as
        explicitly installed.
        """
        if not packages:
            return

        cmd = self._commands.install(packages)

        returncode, pacman_output = command.pty_run(cmd)
        if returncode != 0:
            raise errors.CommandFailedError(cmd, pacman_output)

        self.print_highlighted_pacman_messages(pacman_output)

        cmd = self._commands.set_as_explicit(packages)

        returncode, pacman_output = command.run(cmd)
        if returncode != 0:
            raise errors.CommandFailedError(cmd, pacman_output)

    def install_dependencies(self, deps: set[str]):
        """
        Installs the given dependencies.
        """
        if not deps:
            return

        cmd = self._commands.install_as_dependencies(deps)

        returncode, pacman_output = command.pty_run(cmd)
        if returncode != 0:
            raise errors.CommandFailedError(cmd, pacman_output)

        self.print_highlighted_pacman_messages(pacman_output)

    def install_files(self, files: list[str], as_explicit: set[str]):
        """
        Installs the given files first as dependencies. Then the packages listed in as_explicit are
        installed explicitly.
        """
        if not files:
            return

        cmd = self._commands.install_files_as_dependencies(files)

        returncode, pacman_output = command.pty_run(cmd)
        if returncode != 0:
            raise errors.CommandFailedError(cmd, pacman_output)

        self.print_highlighted_pacman_messages(pacman_output)

        if not as_explicit:
            return

        cmd = self._commands.set_as_explicit(as_explicit)

        returncode, pacman_output = command.run(cmd)
        if returncode != 0:
            raise errors.CommandFailedError(cmd, pacman_output)

    def upgrade(self):
        """
        Upgrades all packages.
        """
        cmd = self._commands.upgrade()

        returncode, pacman_output = command.pty_run(cmd)
        if returncode != 0:
            raise errors.CommandFailedError(cmd, pacman_output)

        self.print_highlighted_pacman_messages(pacman_output)

    def remove(self, packages: set[str]):
        """
        Removes the given packages.
        """
        if not packages:
            return

        cmd = self._commands.remove(packages)

        returncode, pacman_output = command.pty_run(cmd)
        if returncode != 0:
            raise errors.CommandFailedError(cmd, pacman_output)

        self.print_highlighted_pacman_messages(pacman_output)

    def print_highlighted_pacman_messages(self, pacman_output: str):
        """
        Prints lines that contain pacman output keywords.
        """
        if not self._print_highlights:
            return

        output.print_summary("Pacman output highlights:")
        lines = pacman_output.split("\n")
        for index, line in enumerate(lines):
            for keyword in self._keywords:
                if keyword.lower() in line.lower():
                    output.print_summary(f"lines: {index}-{index + 2}")
                    if index >= 1:
                        output.print_continuation(lines[index - 1])
                    output.print_continuation(line)
                    if index + 1 < len(lines):
                        output.print_continuation(lines[index + 1])
                    output.print_continuation("")

                    # Break, as to not print the same line again if it contains multiple keywords
                    break
