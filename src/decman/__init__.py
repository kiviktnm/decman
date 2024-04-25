"""
Module for writing system configurations for decman.
"""

import typing


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
