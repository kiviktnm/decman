"""
Module for writing system configurations for decman.
"""

import typing
import pwd
import grp
import shutil
import os
import subprocess
import decman.error


def sh(sh_cmd: str,
       user: typing.Optional[str] = None,
       env_overrides: typing.Optional[dict[str, str]] = None):
    """
    Shortcut for running a shell command.
    """
    if env_overrides is None:
        env_overrides = {}

    env = os.environ.copy()
    for var, val in env_overrides.items():
        env[var] = val

    if user is None:
        try:
            subprocess.run(sh_cmd, shell=True, check=True, env=env)
        except subprocess.CalledProcessError as e:
            raise decman.error.UserFacingError(
                f"Running user defined shell command '{sh_cmd}' failed."
            ) from e
    else:
        try:
            uid = pwd.getpwnam(user).pw_uid
            gid = pwd.getpwnam(user).pw_gid
        except KeyError as e:
            raise decman.error.UserFacingError(
                f"Running user defined shell command failed because the user {user} doesn't exist."
            ) from e

        with subprocess.Popen(sh_cmd, shell=True, group=gid, user=uid,
                              env=env) as process:
            if process.wait() != 0:
                raise decman.error.UserFacingError(
                    f"Running user shell command '{sh_cmd}' as {user} failed.")


def prg(command: list[str],
        user: typing.Optional[str] = None,
        env_overrides: typing.Optional[dict[str, str]] = None):
    """
    Shortcut for running a program.
    """
    if env_overrides is None:
        env_overrides = {}

    env = os.environ.copy()
    for var, val in env_overrides.items():
        env[var] = val

    if user is None:
        try:
            subprocess.run(command, check=True, env=env)
        except subprocess.CalledProcessError as e:
            raise decman.error.UserFacingError(
                f"Running user defined program '{command}' failed.") from e
    else:
        try:
            uid = pwd.getpwnam(user).pw_uid
            gid = pwd.getpwnam(user).pw_gid
        except KeyError as e:
            raise decman.error.UserFacingError(
                f"Running user defined program failed because the user {user} doesn't exist."
            ) from e

        with subprocess.Popen(command, group=gid, user=uid,
                              env=env) as process:
            if process.wait() != 0:
                raise decman.error.UserFacingError(
                    f"Running user program '{command}' as {user} failed.")


class File:
    """
    A simple file that gets copied to the target.
    """

    def __init__(
        self,
        source_file: typing.Optional[str] = None,
        content: typing.Optional[str] = None,
        bin_file: bool = False,
        encoding: str = "utf-8",
        owner: typing.Optional[str] = None,
        group: typing.Optional[str] = None,
        permissions: int = 0o644,
    ):
        if source_file is None and content is None:
            raise ValueError("Both source_file and content cannot be None.")

        if source_file is not None and content is not None:
            raise ValueError("Both source_file and content cannot be set.")

        self.source_file = source_file
        self.content = content
        self.permissions = permissions
        self.bin_file = bin_file
        self.encoding = encoding
        self.uid = None
        self.gid = None

        if owner is not None:
            self.uid = pwd.getpwnam(owner).pw_uid
            self.gid = pwd.getpwnam(owner).pw_gid

        if group is not None:
            self.gid = grp.getgrnam(group).gr_gid

    def copy_to(self,
                target: str,
                variables: typing.Optional[dict[str, str]] = None):
        """
        Copies the contents of this file to the target file.
        """
        if variables is None:
            variables = {}

        target_directory = os.path.dirname(target)
        os.makedirs(target_directory, exist_ok=True)

        self._write_content(target, variables)

        if self.uid is not None:
            assert self.gid is not None, "If uid is set, then gid is set."
            os.chown(target, self.uid, self.gid)

        os.chmod(target, self.permissions)

    def _write_content(self, target: str, variables: dict[str, str]):
        if self.source_file is not None and (self.bin_file
                                             or len(variables) == 0):
            shutil.copy(self.source_file, target)
        elif self.bin_file and self.content is not None:
            with open(target, "wb") as file:
                file.write(self.content.encode(encoding=self.encoding))
        elif self.source_file is not None:
            with open(self.source_file, "rt", encoding=self.encoding) as src:
                content = src.read()

            for var, value in variables.items():
                content = content.replace(var, value)

            with open(target, "wt", encoding=self.encoding) as file:
                file.write(content)
        else:
            assert self.content is not None, "Content should be set since source_file was not set."
            content = self.content
            for var, value in variables.items():
                content = content.replace(var, value)

            with open(target, "wt", encoding=self.encoding) as file:
                file.write(content)


class Directory:
    """
    Contents of this directory will be copied to the target.
    """

    def __init__(
        self,
        source_directory: str,
        bin_files: bool = False,
        encoding: str = "utf-8",
        owner: typing.Optional[str] = None,
        group: typing.Optional[str] = None,
        permissions: int = 0o644,
    ):
        self.source_directory = source_directory
        self.bin_files = bin_files
        self.encoding = encoding
        self.permissions = permissions

        self.owner = owner
        self.group = group
        self.uid = None
        self.gid = None

        if owner is not None:
            self.uid = pwd.getpwnam(owner).pw_uid
            self.gid = pwd.getpwnam(owner).pw_gid

        if group is not None:
            self.gid = grp.getgrnam(group).gr_gid

    def copy_to(
            self,
            target_directory: str,
            variables: typing.Optional[dict[str, str]] = None) -> list[str]:
        """
        Copies the files in this directory to the target directory.

        Returns all created files.
        """
        created = []
        original_wd = os.getcwd()
        try:
            os.chdir(self.source_directory)
            for src_dir, _, src_files in os.walk("."):
                for src_file in src_files:
                    src_path = os.path.join(src_dir, src_file)
                    file = File(source_file=src_path,
                                bin_file=self.bin_files,
                                encoding=self.encoding,
                                owner=self.owner,
                                group=self.group,
                                permissions=self.permissions)
                    target = os.path.join(target_directory, src_path)
                    created.append(target)
                    file.copy_to(target, variables)
        finally:
            os.chdir(original_wd)
        return created


class UserPackage:
    """
    Defines a custom package.
    """

    def __init__(
        self,
        pkgname: str,
        version: str,
        dependencies: list[str],
        git_url: str,
        pkgbase: typing.Optional[str] = None,
        provides: typing.Optional[list[str]] = None,
        make_dependencies: typing.Optional[list[str]] = None,
        check_dependencies: typing.Optional[list[str]] = None,
    ):
        if pkgbase is None:
            pkgbase = pkgname
        if provides is None:
            provides = []
        if make_dependencies is None:
            make_dependencies = []
        if check_dependencies is None:
            check_dependencies = []

        self.pkgname = pkgname
        self.pkgbase = pkgbase
        self.version = version
        self.provides = provides
        self.dependencies = dependencies
        self.make_dependencies = make_dependencies
        self.check_dependencies = check_dependencies
        self.git_url = git_url

    def __hash__(self) -> int:
        return self.pkgname.__hash__()

    def __eq__(self, value: object, /) -> bool:
        if isinstance(value, self.__class__):
            return value.pkgname == self.pkgname
        return False


class Module:
    """
    Collection of connected packages, services and files.

    Inherit this class to create your own modules.
    """

    def __init__(self, name: str, enabled: bool, version: str):
        self.name = name
        self.enabled = enabled
        self.version = version

    def on_enable(self):
        """
        Override this method to run python code when this module gets enabled.
        """

    def on_disable(self):
        """
        Override this method to run python code when this module gets disabled.

        Note! If this module is simply removed, the code will not exacute. Instead set enabled to
        False.
        """

    def after_update(self):
        """
        Override this method to run python code after updating the system. If this module is
        disabled, this will not run.
        """

    def after_version_change(self):
        """
        Override this method to run python code after the version of this module has changed.
        """

    def files(self) -> dict[str, File]:
        """
        Override this method to return files that should be installed as a part of this module.
        """
        return {}

    def directories(self) -> dict[str, Directory]:
        """
        Override this method to return directories that should be installed as a part of this module.
        """
        return {}

    def file_variables(self) -> dict[str, str]:
        """
        Override this method to return variables that should replaced with a new value inside
        this module's text files.
        """
        return {}

    def pacman_packages(self) -> list[str]:
        """
        Override this method to return pacman packages that should be installed as a part of this
        Module.
        """
        return []

    def user_packages(self) -> list[UserPackage]:
        """
        Override this method to return user packages that should be installed as a part of this
        Module.
        """
        return []

    def aur_packages(self) -> list[str]:
        """
        Override this method to return AUR packages that should be installed as a part of this
        Module.
        """
        return []

    def systemd_units(self) -> list[str]:
        """
        Override this method to return systemd units that should be enabled as a part of this
        Module.
        """
        return []

    def systemd_user_units(self) -> dict[str, list[str]]:
        """
        Override this method to return systemd user units that should be enabled as a part of this
        Module.
        """
        return {}

    def __hash__(self) -> int:
        return self.name.__hash__()

    def __eq__(self, value: object, /) -> bool:
        if isinstance(value, self.__class__):
            return value.name == self.name
        return False


packages: list[str] = []
aur_packages: list[str] = []
user_packages: list[UserPackage] = []
ignored_packages: list[str] = []
enabled_systemd_units: list[str] = []
enabled_systemd_user_units: dict[str, list[str]] = {}
files: dict[str, File] = {}
directories: dict[str, Directory] = {}
modules: list[Module] = []
