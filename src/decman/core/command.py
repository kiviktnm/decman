import errno
import fcntl
import os
import pty
import pwd
import select
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import termios
import tty
import typing

import decman.core.error as errors
import decman.core.output as output


def get_user_info(user: str) -> tuple[int, int]:
    """
    Returns UID and GID of the given user.

    If the user doesn't exist, raises UserNotFoundError.
    """
    info = _get_passwd(user)
    return info.pw_uid, info.pw_gid


def pty_run(
    command: list[str],
    user: None | str = None,
    env_overrides: None | dict[str, str] = None,
    mimic_login: bool = False,
    pass_environment: bool = True,
) -> tuple[int, str]:
    """
    Runs a given command with the given arguments in a pseudo TTY. The command can be ran as
    the given user and environment variables can be overridden manually.

    By default this will copy the current environment and pass it to the process. To prevent this
    set ``pass_environment`` to ``False``.

    If ``mimic_login`` is True, will set the following environment variables according to the given
    user's passwd file details. This only happens when user is set.
        - HOME
        - USER
        - LOGNAME
        - SHELL

    If the given command is empty, returns (0, "").

    Returns the return code of the command and the output as a string.

    If the user doesn't exist, raises UserNotFoundError.
    If forking the process fails or stdin is not a TTY, raises OSError.
    """
    if not command:
        return 0, ""

    if not sys.stdin.isatty():
        raise OSError(errno.ENOTTY, "Stdin is not a TTY.")

    command[0] = shutil.which(command[0]) or command[0]

    output.print_debug(f"Running command '{shlex.join(command)}'")

    env = _build_env(user, env_overrides, mimic_login, pass_environment)

    pid, master_fd = pty.fork()
    if pid == 0:
        _exec_in_child(command, env, user)

    return _run_parent(master_fd, pid)


def run(
    command: list[str],
    user: None | str = None,
    env_overrides: None | dict[str, str] = None,
    mimic_login: bool = False,
    pass_environment: bool = True,
) -> tuple[int, str]:
    """
    Runs a given command with the given arguments. The command can be ran as the given user and
    environment variables can be overridden manually.

    By default this will copy the current environment and pass it to the process. To prevent this
    set ``pass_environment`` to ``False``.

    If mimic_login is True, will set the following environment variables according to the given
    user's passwd file details. This only happens when user is set.
        - HOME
        - USER
        - LOGNAME
        - SHELL

    If the given command is empty, returns (0, "").

    Returns the return code of the command and the output as a string.

    If the user doesn't exist, raises UserNotFoundError.
    """
    if not command:
        return 0, ""

    command[0] = shutil.which(command[0]) or command[0]

    output.print_debug(f"Running command '{shlex.join(command)}'")

    env = _build_env(user, env_overrides, mimic_login, pass_environment)
    uid, gid = None, None

    if user:
        uid, gid = get_user_info(user)

    try:
        process = subprocess.Popen(
            command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, user=uid, group=gid
        )
        stdout, _ = process.communicate()
    except OSError as error:
        # Mirror PTY behavior: "<cmd>: <error>\n" and errno-based exit code
        msg = error.strerror or str(error)
        text_output = f"{command[0]}: {msg}\n"
        code = error.errno if error.errno and error.errno < 128 else 127
        return code, text_output

    return process.returncode, stdout.decode("utf-8", errors="replace")


def check_run_result(command: list[str], result: tuple[int, str]) -> tuple[int, str]:
    """
    Validates the result of a command execution.

    If the command exited with a non-zero return code, raises CommandFailedError
    containing the original command and its captured output.

    Otherwise, returns the result unchanged.
    """
    code, output = result
    if code != 0:
        raise errors.CommandFailedError(command, output)
    return code, output


def _build_env(
    user: None | str,
    env_overrides: None | dict[str, str],
    mimic_login: bool,
    pass_environment: bool,
) -> dict[str, str]:
    env = {}
    output.print_debug(
        f"Command environment is: user={user}, env_overrides={env_overrides},"
        f"mimic_login={mimic_login}, pass_environment={pass_environment}"
    )

    if pass_environment:
        env = os.environ.copy()

    if mimic_login and user:
        pw = _get_passwd(user)
        env.update(
            {
                "HOME": pw.pw_dir,
                "USER": pw.pw_name,
                "LOGNAME": pw.pw_name,
                "SHELL": pw.pw_shell,
            }
        )

    if env_overrides:
        env.update(env_overrides)

    return env


def _exec_in_child(command: list[str], env: dict[str, str], user: None | str) -> typing.NoReturn:
    try:
        if user:
            uid, gid = get_user_info(user=user)
            os.setgid(gid)
            os.setuid(uid)

        os.execve(command[0], command, env)
    except OSError as error:
        try:
            os.write(2, f"{command[0]}: {error.strerror}\n".encode())
        except OSError:
            # Not much can be done, if outputting the failure state fails
            pass
        code = error.errno if (error.errno and error.errno < 128) else 127
        os._exit(code)


def _run_parent(master_fd: int, pid: int) -> tuple[int, str]:
    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()

    # Put stdin into raw mode and save previous termios attributes.
    old_tattr = termios.tcgetattr(stdin_fd)
    tty.setraw(stdin_fd)

    # Helper function to set PTY window size to the current terminal size
    def resize_pty(*args):
        try:
            rows, cols = shutil.get_terminal_size()
            winsz = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsz)
        except OSError:
            # In case the child has exited before the signal handled was de-registered
            pass

    # Set PTY window size to match the current terminal size.
    resize_pty()

    # Handle terminal resizes automatically
    old_winch = signal.getsignal(signal.SIGWINCH)
    signal.signal(signal.SIGWINCH, resize_pty)

    try:
        output_bytes = _relay_pty(master_fd, stdin_fd, stdout_fd)
    finally:
        # Restore stdin termios attributes.
        termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_tattr)
        # Restore previous handler
        signal.signal(signal.SIGWINCH, old_winch)
        os.close(master_fd)

    _, status = os.waitpid(pid, 0)
    exitcode = os.waitstatus_to_exitcode(status)
    output = output_bytes.decode("utf-8", errors="replace").replace("\r\n", "\n")
    return exitcode, output


def _relay_pty(master_fd: int, stdin_fd: int, stdout_fd: int) -> bytes:
    """
    Drive interactive I/O between stdin/stdout and the PTY, capturing output.
    """
    output_chunks: list[bytes] = []

    while True:
        # Wait until process or stdin has data
        rlist, _, _ = select.select([master_fd, stdin_fd], [], [])

        # Capture and echo child process
        if master_fd in rlist:
            try:
                data = os.read(master_fd, 1024)
            except OSError:
                # Child process probably exited, EOF
                break

            output_chunks.append(data)
            try:
                os.write(stdout_fd, data)
            except OSError:
                # stdout closed, ignore
                pass

        # Forward stdin
        if stdin_fd in rlist:
            try:
                data = os.read(stdin_fd, 1024)
                os.write(master_fd, data)
            except OSError:
                # Either stdin EOF -> no data to pass
                # or child died -> wait for master_fd to handle
                pass

    return b"".join(output_chunks)


def _get_passwd(user: str) -> pwd.struct_passwd:
    try:
        return pwd.getpwnam(user)
    except KeyError as error:
        raise errors.UserNotFoundError(user) from error
