import os
import shutil
import sys
import typing

import decman.config as config

# ─────────────────────────────
# Visible (non-ANSI) constants
# ─────────────────────────────

_TAG_TEXT = "[DECMAN]"
_SPACING = "    "
_CONTINUATION_PREFIX_TEXT = f"{_TAG_TEXT}{_SPACING} "

INFO = 1
SUMMARY = 2


# ─────────────────────────────
# Color / formatting helpers
# ─────────────────────────────


def has_ansi_support() -> bool:
    """
    Returns True if the running terminal supports ANSI colors or if colors should be enabled.
    """
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("FORCE_COLOR") is not None:
        return True

    if not sys.stdout.isatty():
        return False

    term = os.environ.get("TERM", "")
    return term not in ("", "dumb")


def _apply_color(code: str, text: str) -> str:
    if not config.color_output:
        return text
    return f"{code}{text}\033[m"


def _tag() -> str:
    if not config.color_output:
        return _TAG_TEXT
    return "[\033[1;35mDECMAN\033[m]"


def _continuation_prefix() -> str:
    return f"{_tag()}{_SPACING} "


def _red(text: str) -> str:
    return _apply_color("\033[91m", text)


def _yellow(text: str) -> str:
    return _apply_color("\033[93m", text)


def _cyan(text: str) -> str:
    return _apply_color("\033[96m", text)


def _green(text: str) -> str:
    return _apply_color("\033[92m", text)


def _gray(text: str) -> str:
    return _apply_color("\033[90m", text)


# ─────────────────────────────
# Printing helpers
# ─────────────────────────────


def print_continuation(msg: str, level: int = SUMMARY):
    """
    Prints a message without a prefix.
    """
    if level == SUMMARY or config.debug_output or not config.quiet_output:
        print(f"{_continuation_prefix()}{msg}")


def print_error(error_msg: str):
    """
    Prints an error message to the user.
    """
    print(f"{_tag()} {_red('ERROR')}: {error_msg}")


def print_warning(msg: str):
    """
    Prints a warning to the user.
    """
    print(f"{_tag()} {_yellow('WARNING')}: {msg}")


def print_summary(msg: str):
    """
    Prints a summary message to the user.
    """
    print(f"{_tag()} {_cyan('SUMMARY')}: {msg}")


def print_info(msg: str):
    """
    Prints a detailed message to the user if verbose output is not disabled.
    """
    if config.debug_output or not config.quiet_output:
        print(f"{_tag()} INFO: {msg}")


def print_debug(msg: str):
    """
    Prints a detailed message to the user if debug messages are enabled.
    """
    if config.debug_output:
        print(f"{_tag()} {_gray('DEBUG')}: {msg}")


# ─────────────────────────────
# List printing
# ─────────────────────────────


def print_list(
    msg: str,
    list_to_print: list[str],
    elements_per_line: typing.Optional[int] = None,
    max_line_width: typing.Optional[int] = None,
    limit_to_term_size: bool = True,
    level: int = SUMMARY,
):
    """
    Prints a summary message to the user along with a list of elements.

    If the list is empty, prints nothing.
    """
    if len(list_to_print) == 0:
        return

    list_to_print = list_to_print.copy()

    if level == SUMMARY:
        print_summary(msg)
    elif level == INFO:
        print_info(msg)

    print_continuation("", level=level)

    if elements_per_line is None:
        elements_per_line = len(list_to_print)

    if max_line_width is None:
        max_line_width = 2**32

    if limit_to_term_size:
        visible_prefix_len = len(_CONTINUATION_PREFIX_TEXT)
        max_line_width = shutil.get_terminal_size().columns - visible_prefix_len

    lines = [list_to_print.pop(0)]
    index = 0
    elements_in_current_line = 1

    while list_to_print:
        next_element = list_to_print.pop(0)

        can_fit_elements = elements_in_current_line + 1 <= elements_per_line
        can_fit_text = len(lines[index]) + len(next_element) <= max_line_width

        if can_fit_text and can_fit_elements:
            lines[index] += f" {next_element}"
            elements_in_current_line += 1
        else:
            lines.append(next_element)
            index += 1
            elements_in_current_line = 1

    for line in lines:
        print_continuation(line, level=level)

    print_continuation("", level=level)


# ─────────────────────────────
# Prompts
# ─────────────────────────────


def prompt_number(
    msg: str,
    min_num: int,
    max_num: int,
    default: typing.Optional[int] = None,
) -> int:
    """
    Prompts the user for an integer.
    """
    while True:
        i = input(f"{_tag()} {_green('PROMPT')}: {msg}").strip()

        if default is not None and i == "":
            return default

        try:
            num = int(i)
            if min_num <= num <= max_num:
                return num
        except ValueError:
            pass

        print_error("Invalid input.")


def prompt_confirm(msg: str, default: typing.Optional[bool] = None) -> bool:
    """
    Prompts the user for confirmation.
    """
    options_suffix = "(y/n)"
    if default is not None:
        options_suffix = "(Y/n)" if default else "(y/N)"

    while True:
        i = input(f"{_tag()} {_green('PROMPT')} {options_suffix}: {msg} ").strip()

        if default is not None and i == "":
            return default

        if i.lower() in ("y", "ye", "yes"):
            return True

        if i.lower() in ("n", "no"):
            return False

        print_error("Invalid input.")
