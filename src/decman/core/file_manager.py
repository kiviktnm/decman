import os
import typing

import decman.core.error as errors
import decman.core.fs as fs
import decman.core.module as module
import decman.core.output as output
import decman.core.store as _store


def update_files(
    store: _store.Store,
    modules: set[module.Module],
    files: dict[str, fs.File],
    directories: dict[str, fs.Directory],
    dry_run: bool = False,
) -> bool:
    output.print_summary("Installing files.")

    all_checked_files = []
    all_changed_files = []
    store.ensure("all_files", [])

    try:
        output.print_debug("Applying common files.")
        checked, changed = _install_files(files, dry_run=dry_run)
        all_checked_files += checked
        all_changed_files += changed

        output.print_debug("Applying common directories.")
        checked, changed = _install_directories(directories, dry_run=dry_run)
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

            if len(module_changed_files) > 0:
                output.print_debug(
                    f"Module '{mod.name}' set to changed due to modified \
                    files: {', '.join(module_changed_files)}"
                )
                mod._changed = True
            all_changed_files += module_changed_files
    except errors.FSInstallationFailedError as error:
        output.print_error(str(error))
        output.print_traceback()
        return False

    to_remove = []
    for file in store["all_files"]:
        if file not in all_checked_files:
            to_remove.append(file)

    output.print_list("Updated files:", all_changed_files, elements_per_line=1)
    output.print_list("Removing files:", to_remove, elements_per_line=1)

    if not dry_run:
        for file in to_remove:
            try:
                os.remove(file)
            except OSError as error:
                output.print_warning(f"Failed to remove file: '{file}': {error.strerror}.")
        store["all_files"] = all_checked_files

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
