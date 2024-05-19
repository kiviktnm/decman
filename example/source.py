# This example covers all decman features and many useful ways of configuring a system.
# Configuration can be as simple or as complex as is needed.

import socket
import os

# Note: Do NOT use from imports for global variables
# BAD: from decman import packages/modules/etc
import decman
import decman.config

# This is fine since the thing being imported is a class and not a global variable.
from decman import UserPackage, File, Directory, UserRaisedError

# Configuring what packages are installed is easy.
# Duplicates are OK, so if you have multiple modules that want to ensure a package is installed,
# you can add the same package multiple times.
decman.packages += ["python", "python", "devtools", "git", "networkmanager"]

# Decman matches installed packages to those defined in the configuration.
# This means that:
# - all packages not installed on the system but defined in the source are installed
# - all packages installed on the system but not defined in the source are removed
# To make decman not care if a package is installed or not, add it to ignored_packages.
# Ignored packages can be normal packages or aur packages.
decman.ignored_packages += ["rustup", "yay"]

# Installing AUR packages is easy.
decman.aur_packages += ["protonvpn"]

# To import GPG keys, set the GNUPGHOME environment variable.
# It can easily be done with python as well.
os.environ["GNUPGHOME"] = "/home/kk/.gnupg/"
# You then must set the user that builds the packages to the owner of the GPG home.
decman.config.makepkg_user = "kk"

# You can also install packages from anywhere, but then you must include some
# information about the package. The git_url is the url to the PKGBUILD,
# This example may not be up to date, but you should keep these up to date with the PKGBUILD.
decman.user_packages.append(
    UserPackage(
        pkgname="decman-git",
        version="0.2.0",
        provides=["decman"],
        dependencies=[
            "python",
            "python-requests",
            "devtools",
            "pacman",
            "systemd",
            "git",
            "less",
        ],
        make_dependencies=[
            "python-setuptools",
            "python-build",
            "python-installer",
            "python-wheel",
        ],
        git_url="https://github.com/kiviktnm/decman-pkgbuild.git",
    ))

# Managing only packages with decman is not that interesting.
# Decman also has really powerful ways of managing config files, scripts etc.

# IMPORTANT: Decman will remove files that were created by decman, but are no longer in the decman source.
# Keep your files in version control to avoid losing important files accidentally.

# Define file content inline.
# Default text file encoding is utf-8 but it can be changed.
decman.files["/etc/vconsole.conf"] = File(content="KEYMAP=us",
                                          encoding="utf-8")

# Include file content from another file, set the file owner and permissions.
# The source_file is relative to the directory where the main decman source.py is located.
# By default, the file group is set to the group of the owner, but it can be overridden with the group argument.
decman.files["/home/kk/.bin/user-script.sh"] = File(
    source_file="files/user-script.sh", owner="kk", permissions=0o744)

# Non-text files such as images can also be managed.
decman.files["/home/kk/.background.png"] = File(
    source_file="files/i-dont-actually-exist.png", bin_file=True, owner="kk")

# If you need to install multiple files at once, use directories.
# All files from the source directory will be copied recursively to the target.
decman.directories["/home/kk/.config/app/"] = Directory(
    source_directory="files/app-config", owner="kk")

# Decman has built in support for managing systemd units as well.
# Decman will enable services declared here, and disable services removed from here.
# If you don't want decman to manage a service, don't add it here. It will ignore all units that
# weren't enabled here.
decman.enabled_systemd_units += ["NetworkManager.service"]

# You can manage units for users as well.

# Ensure that previous user unit declarations aren't overwritten and they are initialized.
decman.enabled_systemd_user_units[
    "kk"] = decman.enabled_systemd_user_units.get("kk", [])
# Add user unit.
decman.enabled_systemd_user_units["kk"].append("syncthing.service")

# Most powerful feature of decman are modules.
# In this file you see how to include your module, but to really see what modules are capable of
# look at the MyModule class.
from my_module import MyModule

my_own_mod = MyModule()

# You have full access to python, which makes your configuration very dynamic.
# For example: do something if the computers hostname is arch-1
if socket.gethostname() == "arch-1":
    # Modules make dynamic configuration easy.
    # This executes code defined in MyModule which can affect for example what packages are
    # installed as a part of this module.
    my_own_mod.enable_my_custom_feature(True)
else:
    # If you want to abort running decman from your config because something is wrong, raise a UserRaisedError
    raise UserRaisedError("Unknown hostname!")

decman.modules += [my_own_mod]

# Configuring the behavior of decman is also done here.
# These are the default values.

# Note: you probably don't want to change these 2 settings and instead you'll want to to use the --debug CLI option.
# Show debug output
decman.config.debug_output = False
# Suppress output of some commands that you probably don't want to see.
decman.config.suppress_command_output = True

# Make output less verbose. Summaries are still printed.
decman.config.quiet_output = False

# The user which builds aur and user packages.
# decman.config.makepkg_user = "nobody" # This was set in a previous example. Let's not override it.

# The build directory decman uses for creating a chroot etc.
decman.config.build_dir = "/tmp/decman/build"

# Built packages are stored here.
decman.config.pkg_cache_dir = "/var/cache/decman"

# Timeout in seconds for fetching aur package details.
decman.config.aur_rpc_timeout = 30

# Enable installing and upgrading foreign packages.
decman.config.enable_fpm = True

# Number of package files per package kept in the cache
# All built AUR packages and user packages are stored in cache.
decman.config.number_of_packages_stored_in_cache = 3


# Changing the default commands decman uses for things is a bit more complex.
# Create a child class of the decman.config.Commands class and override methods.
# These are the defaults.
class MyCommands(decman.config.Commands):

    def list_pkgs(self) -> list[str]:
        return ["pacman", "-Qeq", "--color=never"]

    def list_foreign_pkgs_versioned(self) -> list[str]:
        return ["pacman", "-Qm", "--color=never"]

    def install_pkgs(self, pkgs: list[str]) -> list[str]:
        return ["pacman", "-S", "--needed"] + pkgs

    def install_files(self, pkg_files: list[str]) -> list[str]:
        return ["pacman", "-U", "--asdeps"] + pkg_files

    def set_as_explicitly_installed(self, pkgs: list[str]) -> list[str]:
        return ["pacman", "-D", "--asexplicit"] + pkgs

    def install_deps(self, deps: list[str]) -> list[str]:
        return ["pacman", "-S", "--needed", "--asdeps"] + deps

    def is_installable(self, pkg: str) -> list[str]:
        return ["pacman", "-Sddp", pkg]

    def upgrade(self) -> list[str]:
        return ["pacman", "-Syu"]

    def remove(self, pkgs: list[str]) -> list[str]:
        return ["pacman", "-Rs"] + pkgs

    def enable_units(self, units: list[str]) -> list[str]:
        return ["systemctl", "enable"] + units

    def disable_units(self, units: list[str]) -> list[str]:
        return ["systemctl", "disable"] + units

    def enable_user_units(self, units: list[str], user: str) -> list[str]:
        return ["systemctl", "--user", "-M", f"{user}@", "enable"] + units

    def disable_user_units(self, units: list[str], user: str) -> list[str]:
        return ["systemctl", "--user", "-M", f"{user}@", "disable"] + units

    def compare_versions(self, installed_version: str,
                         new_version: str) -> list[str]:
        return ["vercmp", installed_version, new_version]

    def git_clone(self, repo: str, dest: str) -> list[str]:
        return ["git", "clone", repo, dest]

    def git_diff(self, from_commit: str) -> list[str]:
        return ["git", "diff", from_commit]

    def git_get_commit_id(self) -> list[str]:
        return ["git", "rev-parse", "HEAD"]

    def review_file(self, file: str) -> list[str]:
        return ["less", file]

    def make_chroot(self, chroot_dir: str, with_pkgs: list[str]) -> list[str]:
        return ["mkarchroot", chroot_dir] + with_pkgs

    def install_chroot_packages(self, chroot_dir: str, packages: list[str]):
        return [
            "arch-nspawn", chroot_dir, "pacman", "-S", "--needed",
            "--noconfirm"
        ] + packages

    def remove_chroot_packages(self, chroot_dir: str, packages: list[str]):
        return ["arch-nspawn", chroot_dir, "pacman", "-Rsu", "--noconfirm"
                ] + packages

    def make_chroot_pkg(self, chroot_wd_dir: str, user: str,
                        pkgfiles_to_install: list[str]) -> list[str]:
        makechrootpkg_cmd = [
            "makechrootpkg", "-c", "-r", chroot_wd_dir, "-U", user
        ]

        for pkgfile in pkgfiles_to_install:
            makechrootpkg_cmd += ["-I", pkgfile]

        return makechrootpkg_cmd


# To apply your overrides, set the commands variable.
decman.config.commands = MyCommands()

# Alternative to the built in AUR support:
# If you don't want to use the built in AUR helper, you can use some pacman wrapper that can run as root, such as pikaur.
# To do this, override commands and disable fpm.


class PikaurWrapperCommands(decman.config.Commands):

    def list_pkgs(self) -> list[str]:
        return ["pikaur", "-Qeq"]

    def install_pkgs(self, pkgs: list[str]) -> list[str]:
        return ["pikaur", "-S"] + pkgs

    def upgrade(self) -> list[str]:
        return ["pikaur", "-Syu"]

    def remove(self, pkgs: list[str]) -> list[str]:
        return ["pikaur", "-Rs"] + pkgs

    # it doesn't matter if all pacman commands aren't overridden since they wont be used when fpm is disabled.


# decman.config.enable_fpm = False
# decman.config.commands = PikaurWrapperCommands()

# Then simply add all AUR packages to decman.packages
# decman.packages += ["pikaur"]
