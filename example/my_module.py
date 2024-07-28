# from import is ok for importing classes and functions
# just remember to not import variables this way
from decman import Module, File, Directory, UserPackage, sh, prg


class MyModule(Module):

    def __init__(self):
        self.pkgs = ["rust"]
        self.update_rustup = False
        # Modules have names and versions.
        # Names must be unique.

        # If you disable a module, all packages, files etc assocated with module are removed.
        super().__init__(name="Example module", enabled=True, version="1")

    # You can add any methods etc to your modules.
    def enable_my_custom_feature(self, b: bool):
        if b:
            self.pkgs = ["rustup"]
            self.update_rustup = True

    # This is ran, when the module gets enabled
    def on_enable(self):
        # Run arbitary shell code easily with the included sh function.
        sh("groupadd mygroup")

        # or run a program with arguments.
        prg(["usermod", "--append", "--groups", "mygroup", "kk"])

    def on_disable(self):
        # You can run commands as any user
        sh("whoami", user="kk")

        # And override environment variables
        sh("echo $HI", env_overrides={"HI": "Hello!"})

        # Same options apply to prg as well.

    def after_update(self):
        # Run code after running decman.
        if self.update_rustup:
            prg(["rustup", "update"], user="kk")

    def after_version_change(self):
        # Modules have version numbers to allow conditionally running code.
        # You could for example run mkinitcpio only after your config has changed.
        # Just remember to change the version number.
        prg(["mkinitcpio", "-P"])

    # Files defined here are the same as outside of modules.
    # There is however an additional feature:
    # You may add variables to text files, that will be replaced with the given value.

    def file_variables(self) -> dict[str, str]:
        return {"%msg%": "Hello, world!"}

    def files(self) -> dict[str, File]:
        # Variables are substituted in text files automatically.
        return {
            "/usr/local/bin/say-hello":
            File(content="#!/usr/bin/env bash\necho %msg%", permissions=0o755),
            # Variables are not substituted in binary files.
            "/usr/local/share/say-hello/image.png":
            File(source_file="files/i-dont-exist.png", bin_file=True),
        }

    def directories(self) -> dict[str, Directory]:
        # Directories are handeled the same way. Variables are substituted in text files.
        return {
            "/home/kk/.config/mod-app/":
            Directory(source_directory="files/app-config", owner="kk")
        }

    # Packages and systemd units are basically the same with modules as without modules.

    def pacman_packages(self) -> list[str]:
        # Return pacman packages depending on the usage of this module.
        return self.pkgs

    def user_packages(self) -> list[UserPackage]:
        return [
            UserPackage(
                pkgname="decman-git",
                version="0.3.1",
                provides=["decman"],
                dependencies=[
                    "python",
                    "python-requests",
                    "devtools",
                    "systemd",
                    "pacman",
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
            )
        ]

    def aur_packages(self) -> list[str]:
        return ["protonvpn"]

    def systemd_units(self) -> list[str]:
        return ["reflector.timer"]

    def systemd_user_units(self) -> dict[str, list[str]]:
        return {"kk": ["syncthing.service"]}
