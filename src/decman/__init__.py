import shlex
import typing

import decman.core.command as command
import decman.core.output as output

# Re-exports
from decman.core.error import SourceError
from decman.core.fs import Directory, File
from decman.core.module import Module
from decman.plugins import Plugin, available_plugins

# Plugin types
from decman.plugins.pacman import Pacman
from decman.plugins.systemd import Systemd

__all__ = [
    "SourceError",
    "File",
    "Directory",
    "Module",
    "Plugin",
    "prg",
    "sh",
]

# -----------------------------------------
# Global variables for system configuration
# -----------------------------------------
files: dict[str, File] = {}
directories: dict[str, Directory] = {}
modules: set[Module] = set()
plugins: dict[str, Plugin] = available_plugins()
execution_order: list[str] = [
    "files",
    "pacman",
    "aur",
    "flatpak",
    "systemd",
]

# Default plugins get quick access
pacman: None | Pacman = None
systemd: None | Systemd = None

_pacman = plugins.get("pacman", None)
if isinstance(_pacman, Pacman):
    pacman = _pacman

_systemd = plugins.get("systemd", None)
if isinstance(_systemd, Systemd):
    systemd = _systemd


def prg(
    cmd: list[str],
    user: typing.Optional[str] = None,
    env_overrides: typing.Optional[dict[str, str]] = None,
    mimic_login: bool = False,
    pty: bool = True,
    check: bool = True,
) -> str:
    """
    Shortcut for running a command. Returns the output of that command.

    Arguments:
        cmd:
            Command to execute.

        user:
            User name to run the command as. If set, the command is executed after dropping
            privileges to this user.

        env_overrides:
            Environment variables to override or add for the command execution.
            These values are merged on top of the current process environment.

        mimic_login:
            If mimic_login is True, will set the following environment variables according to the
            given user's passwd file details. This only happens when user is set.
                - HOME
                - USER
                - LOGNAME
                - SHELL

        pty:
            If True, run the command inside a pseudo-terminal (PTY). This enables interactive
            behavior and terminal-dependent programs. If False, run the command without a PTY
            using standard subprocess execution.

        check:
            If True, raise CommandFailedError when the command exits with a non-zero status.
            If False, print a warning when encountering a non-zero exit code.
    """
    if pty:
        result = command.pty_run(
            cmd, user=user, env_overrides=env_overrides, mimic_login=mimic_login
        )
    else:
        result = command.run(cmd, user=user, env_overrides=env_overrides, mimic_login=mimic_login)

    if check:
        # This raises an error if the command failed exiting the function early
        result = command.check_run_result(cmd, result)

    code, command_output = result
    if code != 0:
        output.print_warning(f"Command '{shlex.join(cmd)}' returned with an exit code {code}.")

    return command_output


def sh(
    sh_cmd: str,
    user: typing.Optional[str] = None,
    env_overrides: typing.Optional[dict[str, str]] = None,
    mimic_login: bool = False,
    pty: bool = True,
    check: bool = True,
) -> str:
    """
    Shortcut for running a shell command. Returns the output of that command.

    Arguments:
        sh_cmd:
            Shell command to execute. The command is passed to the system shell /bin/sh.

        user:
            User name to run the command as. If set, the command is executed after dropping
            privileges to this user.

        env_overrides:
            Environment variables to override or add for the command execution.
            These values are merged on top of the current process environment.

        mimic_login:
            If mimic_login is True, will set the following environment variables according to the
            given user's passwd file details. This only happens when user is set.
                - HOME
                - USER
                - LOGNAME
                - SHELL

        pty:
            If True, run the command inside a pseudo-terminal (PTY). This enables interactive
            behavior and terminal-dependent programs. If False, run the command without a PTY
            using standard subprocess execution.

        check:
            If True, raise CommandFailedError when the command exits with a non-zero status.
            If False, print a warning when encountering a non-zero exit code.
    """
    cmd = ["/bin/sh", "-c", sh_cmd]
    return prg(
        cmd, user=user, env_overrides=env_overrides, mimic_login=mimic_login, pty=pty, check=check
    )
