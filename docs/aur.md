# AUR

> [!NOTE]
> While this plugin exists with the sole purpose of installing foreing packages, this functionality is not the primary purpose of decman. Issues regarding this plugin are not a priority.
> If you can't build a package with this plugin, consider adding it to `ignored_packages` and building it yourself.

AUR plugin can be used to manage AUR and custom packages. The pacman plugin manages only foreing packages installed from the AUR or elsewhere. All native (pacman repositories) packages are ignored by this plugin with the exception that this plugin will install native dependencies of foreign packages.

It manages packages exactly the same way as the pacman plugin.

> This plugin will ensure that explicitly installed packages match those defined in the decman source. If your system has explicitly installed package A, but it is not included in the source, it will be uninstalled. You don't need to list dependencies in your source as those will be handeled by pacman automatically. However, if you have inluded package B in your source and that package depends on A, this plugin will not remove A. Instead it will demote A to a dependency. This plugin will also remove all orphaned packages automatically.

Building of foreign packages happens in a chroot. This creates some overhead, but ensures clean builds. By default the chroot is created to `/tmp/decman/build`. If `/tmp` is a in-memory filesystem like tmpfs, make sure that the tmpfs-partition is large enough. I recommend at least 6 GB. You can also change the build directory if memory is an issue.

Build packages are by default stored in a cache `/var/cache/decman/aur`. This plugin keeps 3 most recent versions of all packages.

When installing packages from other version control systems than git, you'll need to install the package for that VCS. There is an [issue and a workaround](source) related to fossil packages. Note that the issue's workaround is for an old version of decman. With this version, set the `makepkg_user` with `decman.aur.makepkg_user`.

## Usage

Define AUR packages. These will be installed from the AUR.

```py
import decman
decman.aur.packages |= {"android-studio", "fnm-bin"}
```

Define ignored foreing packages. These can be AUR packages or other foreign packages. These packages will never get installed or removed by the plugin.

```py
decman.aur.ignored_packages |= {"yay"}
```

Define packages from custom sources. Add a package name and repository / directory containing a PKGBUILD. This plugin will fetch the PKGBUILD, generate .SRCINFO and parse that to find the package details.

```py
from decman.plugins.aur import CustomPackage
decman.aur.custom_packages |= {
    CustomPackage("decman", git_url="https://github.com/kiviktnm/decman-pkgbuild.git"),
    CustomPackage("my-own-package", pkgbuild_directory="/path/to/directory/"),
}
```

This plugin's execution order step name is `aur`.

### Command line

This plugin accepts params via the command line.

```sh
sudo decman --params aur-upgrade-devel aur-force
```

`aur-upgrade-devel` causes devel packages (packages from version control, such as `*-git` packages) to be upgraded.

`aur-force` causes decman to rebuild packages that were already cached.

### Within modules

Modules can also define AUR packages and custom packages. Decorate a module's method with `@decman.plugins.aur.packages` or `@decman.plugins.aur.custom_packages`. For AUR packages return a `set[str]` of package names from that module. Custom packages should return a `set[CustomPackage]`.

```py
import decman
from decman.plugins import aur

class MyModule(decman.Module):
    ...

    @aur.packages
    def aur_packages_defined_in_this_module(self) -> set[str]:
        return {"android-studio", "fnm-bin"}

    @aur.custom_packages
    def custom_packages_defined_in_this_module(self) -> set[aur.CustomPackage]:
        return {
            CustomPackage("decman", git_url="https://github.com/kiviktnm/decman-pkgbuild.git"),
        }
```

If these sets change, this plugin will flag the module as changed. The module's `on_change` method will be executed.

## Configuration

This module has partially the same configuration with pacman. You'll have to define pacman output keywords again.

```py
import decman
# set keywords
decman.aur.keywords = {"pacsave", "pacnew", "warning"}
# disable the feature
decman.aur.print_highlights = False
```

There are some options related to building packages.

```py
# Timeout for fetching information from AUR
decman.aur.aur_rpc_timeout = 30
# User which builds AUR packages
decman.aur.makepkg_user = "nobody"
# Directory used for building packages
decman.aur.build_dir = "/tmp/decman/build"
```

Some AUR packages must be verified with GPG keys. In that case set the `GNUPGHOME` environment variable to the keystore containing imported keys. Set `makepkg_user` user to the owner of that directory.

```py
import os
os.environ["GNUPGHOME"] = "/home/kk/.gnupg/"
decman.aur.makepkg_user = "kk"
```

Additionally it's possible to override the commands this plugin uses. Create your own `AurCommands` class and override methods returning commands. Since this plugin and the pacman plugin have many overlapping commands, `AurCommands` is actually a subclass of `PacmanCommands`. This means that you can use a single override class for both of them. These are the defaults.

```py
from decman.plugins import aur
import decman

class MyAurAndPacmanCommands(aur.AurCommands):
    def list_orphans_foreign(self) -> list[str]:
        """
        Running this command outputs a newline seperated list of orphaned foreign packages.
        """
        return ["pacman", "-Qmdtq", "--color=never"]

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

    # -------------------------------------------
    # Here I override some PacmanCommand methods.
    # -------------------------------------------

    def set_as_explicit(self, pkgs: set[str]) -> list[str]:
        """
        Running this command sets the given as explicitly installed.
        """
        return ["pacman", "-D", "--asexplicit"] + list(pkgs)

    def set_as_dependencies(self, pkgs: set[str]) -> list[str]:
        """
        Running this command sets the given packages as dependencies.
        """
        return ["pacman", "-D", "--asdeps"] + list(pkgs)
```

Applying the commands is easy.

```py
import decman
decman.pacman.commands = MyAurAndPacmanCommands()
decman.aur.commands = MyAurAndPacmanCommands()
```
