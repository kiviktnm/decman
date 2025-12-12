"""
Module for decman errors.
"""


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
