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
