import os
import typing

import decman.core.error as errors
import decman.core.fs as fs
import decman.core.module as module
import decman.core.output as output
import decman.core.store as _store


def update_files(
    store: _store.Store,
    modules: list[module.Module],
    files: dict[str, fs.File],
    directories: dict[str, fs.Directory],
    symlinks: dict[str, str],
    dry_run: bool = False,
) -> bool:
    """
    Apply the desired file and directory state.

    Installs common and module-provided files and directories, tracks all checked paths, detects
    changes, removes files no longer managed, and updates the store.

    On failure, no removals are performed and the store is left unchanged.

    Arguments:
        store:
            Persistent store used to track managed file paths.

        modules:
            Enabled modules providing additional files and directories.

        files:
            Common files to install (target path -> File).

        directories:
            Common directories to install (target path -> Directory).

        dry_run:
            If True, perform change detection only without modifying the filesystem.

    Returns:
        True if all operations completed successfully, False if installation failed.
    """
    all_checked_files = []
    all_changed_files = []
    store.ensure("all_files", [])

    output.print_summary("Updating files.")

    try:
        output.print_debug("Applying common files.")
        checked, changed = _install_files(files, dry_run=dry_run)
        all_checked_files += checked
        all_changed_files += changed

        output.print_debug("Applying common directories.")
        checked, changed = _install_directories(directories, dry_run=dry_run)
        all_checked_files += checked
        all_changed_files += changed

        output.print_debug("Applying common symlinks.")
        checked, changed = _install_symlinks(symlinks, dry_run=dry_run)
        all_checked_files += checked
        all_changed_files += changed

        for mod in modules:
            module_changed_files = []

            output.print_debug(f"Applying files in module '{mod.name}'.")
            checked, changed = _install_files(
                mod.files(),
                variables=mod.file_variables(),
                dry_run=dry_run,
            )
            all_checked_files += checked
            module_changed_files += changed

            output.print_debug(f"Applying directories in module '{mod.name}'.")
            checked, changed = _install_directories(
                mod.directories(),
                variables=mod.file_variables(),
                dry_run=dry_run,
            )
            all_checked_files += checked
            module_changed_files += changed

            output.print_debug(f"Applying symlinks in module '{mod.name}'.")
            checked, changed = _install_symlinks(
                mod.symlinks(),
                dry_run=dry_run,
            )
            all_checked_files += checked
            module_changed_files += changed

            if len(module_changed_files) > 0:
                output.print_debug(
                    f"Module '{mod.name}' set to changed due to modified "
                    f"files: '{"', '".join(module_changed_files)}'."
                )
                mod._changed = True
            all_changed_files += module_changed_files
    except errors.FSInstallationFailedError as error:
        output.print_error(str(error))
        output.print_traceback()
        return False
    except errors.FSSymlinkFailedError as error:
        output.print_error(str(error))
        output.print_traceback()
        return False

    to_remove = []
    for file in store["all_files"]:
        if file not in all_checked_files:
            to_remove.append(file)

    output.print_list("Updated files:", all_changed_files, elements_per_line=1)

    if not dry_run:
        for file in to_remove:
            try:
                os.remove(file)
            except OSError as error:
                output.print_warning(f"Failed to remove file: '{file}': {error.strerror}.")
        store["all_files"] = all_checked_files

    output.print_list("Removed files:", to_remove, elements_per_line=1)

    return True


def _install_files(
    files: dict[str, fs.File],
    variables: typing.Optional[dict[str, str]] = None,
    dry_run: bool = False,
) -> tuple[list[str], list[str]]:
    checked_files = []
    changed_files = []

    for target_filename, file in files.items():
        output.print_debug(f"Checking file {target_filename}.")
        checked_files.append(target_filename)

        try:
            if file.copy_to(target_filename, variables=variables, dry_run=dry_run):
                changed_files.append(target_filename)
        except FileNotFoundError as error:
            raise errors.FSInstallationFailedError(
                file.source_file or "content", target_filename, "Source file doesn't exist."
            ) from error
        except OSError as error:
            raise errors.FSInstallationFailedError(
                file.source_file or "content", target_filename, error.strerror or str(error)
            ) from error
        except UnicodeEncodeError as error:
            raise errors.FSInstallationFailedError(
                file.source_file or "content", target_filename, "Unicode encoding failed."
            ) from error
        except UnicodeDecodeError as error:
            raise errors.FSInstallationFailedError(
                file.source_file or "content", target_filename, "Unicode decoding failed."
            ) from error

    return checked_files, changed_files


def _install_directories(
    directories: dict[str, fs.Directory],
    variables: typing.Optional[dict[str, str]] = None,
    dry_run: bool = False,
) -> tuple[list[str], list[str]]:
    checked_files = []
    changed_files = []

    for target_dirname, directory in directories.items():
        output.print_debug(f"Checking directory {target_dirname}.")
        try:
            checked, changed = directory.copy_to(
                target_dirname, variables=variables, dry_run=dry_run
            )
        except FileNotFoundError as error:
            raise errors.FSInstallationFailedError(
                directory.source_directory,
                target_dirname,
                "Source directory doesn't exist.",
            ) from error
        except OSError as error:
            raise errors.FSInstallationFailedError(
                directory.source_directory, target_dirname, error.strerror or str(error)
            ) from error
        except UnicodeEncodeError as error:
            raise errors.FSInstallationFailedError(
                directory.source_directory, target_dirname, "Unicode encoding failed."
            ) from error
        except UnicodeDecodeError as error:
            raise errors.FSInstallationFailedError(
                directory.source_directory, target_dirname, "Unicode decoding failed."
            ) from error

        checked_files += checked
        changed_files += changed

    return checked_files, changed_files


def _is_symlink_to(path: str, target: str) -> bool:
    if not os.path.islink(path):
        return False
    return os.readlink(path) == target


def _install_symlinks(
    symlinks: dict[str, str], dry_run: bool = False
) -> tuple[list[str], list[str]]:
    checked_files = []
    changed_files = []

    for link_name, target in symlinks.items():
        output.print_debug(f"Checking symlink {link_name}.")
        try:
            checked_files.append(link_name)

            if _is_symlink_to(link_name, target):
                continue

            changed_files.append(link_name)

            if dry_run:
                continue

            if os.path.lexists(link_name):
                os.unlink(link_name)

            os.makedirs(os.path.dirname(link_name), exist_ok=True)
            os.symlink(target, link_name)
        except OSError as error:
            raise errors.FSSymlinkFailedError(
                link_name, target, error.strerror or str(error)
            ) from error

    return checked_files, changed_files
