class ForeignPackageManagerError(Exception):
    """
    Error raised from the ForeignPackageManager
    """


class DependencyCycleError(Exception):
    """
    Error raised when a dependency cycle is detected involving foreign packages.
    """

    def __init__(self, package1: str, package2: str):
        super().__init__(
            f"Foreign package dependency cycle detected involving '{package1}' "
            f"and '{package2}'. Foreign package dependencies are also required "
            "during package building and therefore dependency cycles cannot be handled."
        )


class PKGBUILDParseError(Exception):
    """
    Error raised when parsing a PKGBUILD fails.
    """

    def __init__(self, git_url: str | None, pkgbuild_directory: str | None, message: str) -> None:
        # Only one of these should be set
        self.pkgbuild_source = git_url or pkgbuild_directory
        self.message = message
        super().__init__(f"Failed to parse PKGBUILD from '{self.pkgbuild_source}': {message}")


class AurRPCError(Exception):
    """
    Error raised when accessing AUR RPC fails.
    """

    def __init__(self, message: str, url: str):
        self.message = message
        self.url = url
        super().__init__(f"Failed to complete AUR RPC request to '{url}': {message}")
