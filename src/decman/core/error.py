"""
Module for decman errors.
"""


class SourceError(Exception):
    """
    Error raised manually from the user's source.
    """

    def __init__(self, message):
        super().__init__(message)


class FSInstallationFailedError(Exception):
    """
    Error raised when trying to install a file/directory to a target.
    """

    def __init__(self, target: str, source: str, reason: str):
        self.source = source
        self.target = target
        super().__init__(f"Failed to install file from {source} to {target}: {reason}")


class InvalidOnDisableError(Exception):
    """
    Error raised when trying to create a Module with an invalid on_disable method.
    """

    def __init__(self, module: str, reason: str):
        self.module = module
        self.reason = reason
        super().__init__(
            f"Module '{module}' contains an invalid on_disable method. Reason: {reason}."
        )


class UserNotFoundError(Exception):
    """
    Raised when a specified user cannot be found in the system.

    Attributes:
        user (str): The user that caused the exception.
    """

    def __init__(self, user: str) -> None:
        self.user = user
        super().__init__(f"The user '{user}' doesn't exist.")


class GroupNotFoundError(Exception):
    """
    Raised when a specified group cannot be found in the system.

    Attributes:
        group (str): The group that caused the exception.
    """

    def __init__(self, group: str) -> None:
        self.group = group
        super().__init__(f"The group '{group}' doesn't exist.")


class CommandFailedError(Exception):
    """
    Raised when running a command failed.

    Attributes:
        command (list[str]): The command that caused the exception.
    """

    def __init__(self, command: list[str], output: str) -> None:
        self.command = command
        self.output = output
        super().__init__(f"Running a command '{' '.join(command)}' failed. Output: '{output}'.")
