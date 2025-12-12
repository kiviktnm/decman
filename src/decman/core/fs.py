import grp
import os
import shutil
import typing

import decman.core.command as command
import decman.core.error as errors


class File:
    """
    Declarative file specification describing how a file should be materialized at a target path.

    Exactly one of ``source_file`` or ``content`` must be provided.

    The file can be created by copying an existing source file or by writing provided content. For
    text files, optional variable substitution is applied at copy time. Binary files are copied or
    written verbatim and never undergo substitution.

    Ownership, permissions, and parent directories are enforced on creation. Missing parent
    directories are created recursively and assigned the same ownership as the file when specified.

    Parameters:
        ``source_file``:
            Path to an existing file to copy from. Mutually exclusive with ``content``.

        ``content``:
            In-memory file contents to write. Mutually exclusive with ``source_file``.

        ``bin_file``:
            If ``True``, treat the file as binary. Disables variable substitution and writes bytes
            verbatim.

        ``encoding``:
            Text encoding used when reading or writing non-binary files.

        ``owner``:
            System user name to own the file and created parent directories.

        ``group``:
            System group name to own the file and created parent directories.

        ``permissions``:
            File mode applied to the target file (e.g. ``0o644``).

    Raises:
        ``ValueError``
            If both ``source_file`` and ``content`` are ``None`` or if both are set.

        ``UserNotFoundError``
            If ``owner`` does not exist on the system.

        ``GroupNotFoundError``
            If ``group`` does not exist on the system.

    Notes:
        Variable substitution is a simple string replacement where each key in ``variables`` is
        replaced by its corresponding value. No escaping or templating semantics are applied.
    """

    def __init__(
        self,
        source_file: typing.Optional[str] = None,
        content: typing.Optional[str] = None,
        bin_file: bool = False,
        encoding: str = "utf-8",
        owner: typing.Optional[str] = None,
        group: typing.Optional[str] = None,
        permissions: int = 0o644,
    ):
        if source_file is None and content is None:
            raise ValueError("Both source_file and content cannot be None.")

        if source_file is not None and content is not None:
            raise ValueError("Both source_file and content cannot be set.")

        self.source_file = source_file
        self.content = content
        self.permissions = permissions
        self.bin_file = bin_file
        self.encoding = encoding
        self.uid = None
        self.gid = None

        if owner is not None:
            self.uid, self.gid = command.get_user_info(owner)

        if group is not None:
            try:
                self.gid = grp.getgrnam(group).gr_gid
            except KeyError as error:
                raise errors.GroupNotFoundError(group) from error

    def copy_to(self, target: str, variables: typing.Optional[dict[str, str]] = None) -> bool:
        """
        Copies the contents of this file to the target file if they differ.

        Parameters:
            target:
                Path to the target file on disk.

            variables:
                Optional mapping of literal substrings to replace in the text content before
                writing. Ignored for binary files and when ``bin_file`` is True.

        Returns:
            True if the file contents were created or modified.
            False if the existing file already contained the desired contents.

        Raises:
            OSError
                If directory creation, file I/O, permission changes, or ownership changes fail
                (e.g. permission denied, missing parent path components, I/O errors).

            FileNotFoundError
                If ``source_file`` is set and does not exist.

            UnicodeDecodeError
                If a text file cannot be decoded using ``encoding``.

            UnicodeEncodeError
                If text content cannot be encoded using ``encoding``.
        """
        if variables is None:
            variables = {}

        target_directory = os.path.dirname(target)

        def create_missing_dirs(dirct: str, uid: typing.Optional[int], gid: typing.Optional[int]):
            if not os.path.isdir(dirct):
                parent_dir = os.path.dirname(dirct)
                if not os.path.isdir(parent_dir):
                    create_missing_dirs(parent_dir, uid, gid)
                os.mkdir(dirct)

                if uid is not None:
                    assert gid is not None, "If uid is set, then gid is set."
                    os.chown(dirct, uid, gid)

        create_missing_dirs(target_directory, self.uid, self.gid)

        changed = self._write_content(target, variables)

        if self.uid is not None:
            assert self.gid is not None, "If uid is set, then gid is set."
            os.chown(target, self.uid, self.gid)

        os.chmod(target, self.permissions)
        return changed

    def _write_content(self, target: str, variables: dict[str, str]):
        # Case 1: copy from source file directly (binary or no substitutions)
        if self.source_file is not None and (self.bin_file or len(variables) == 0):
            if os.path.exists(target):
                with open(self.source_file, "rb") as src, open(target, "rb") as dst:
                    if src.read() == dst.read():
                        return False
            shutil.copy(self.source_file, target)
            return True

        # Case 2: binary content from memory
        if self.bin_file and self.content is not None:
            desired_bytes = self.content.encode(encoding=self.encoding)
            if os.path.exists(target):
                with open(target, "rb") as file:
                    if file.read() == desired_bytes:
                        return False
            with open(target, "wb") as file:
                file.write(desired_bytes)
            return True

        # From here on: text modes with possible substitutions

        # Case 3: text content from source file with substitutions
        if self.source_file is not None:
            with open(self.source_file, "rt", encoding=self.encoding) as src:
                content = src.read()

            for var, value in variables.items():
                content = content.replace(var, value)

            if os.path.exists(target):
                with open(target, "rt", encoding=self.encoding) as file:
                    if file.read() == content:
                        return False

            with open(target, "wt", encoding=self.encoding) as file:
                file.write(content)
            return True

        # Case 4: text content from in-memory string with substitutions
        assert self.content is not None, "Content should be set since source_file was not set."
        content = self.content
        for var, value in variables.items():
            content = content.replace(var, value)

        if os.path.exists(target):
            with open(target, "rt", encoding=self.encoding) as file:
                if file.read() == content:
                    return False

        with open(target, "wt", encoding=self.encoding) as file:
            file.write(content)
        return True


class Directory:
    """
    Declarative specification for copying the contents of a source directory into a target
    directory.

    Files are copied using the :class:`File` abstraction, inheriting its ownership,
    permissions, encoding, and binary/text behavior. Text files can optionally undergo
    variable substitution before being written.

    Parameters:
        ``source_directory``:
            Path to the directory whose contents will be mirrored into the target.

        ``bin_files``:
            If ``True``, treat all files as binary; disables variable substitution and copies bytes
            verbatim.

        ``encoding``:
            Text encoding used when reading or writing non-binary files.

        ``owner``:
            System user name to own created files and directories.

        ``group``:
            System group name to own created files and directories.

        ``permissions``:
            File mode applied to created or updated files (e.g. ``0o644``).

    Raises:
        ``UserNotFoundError``
            If ``owner`` does not exist on the system.

        ``GroupNotFoundError``
            If ``group`` does not exist on the system.
    """

    def __init__(
        self,
        source_directory: str,
        bin_files: bool = False,
        encoding: str = "utf-8",
        owner: typing.Optional[str] = None,
        group: typing.Optional[str] = None,
        permissions: int = 0o644,
    ):
        self.source_directory = source_directory
        self.bin_files = bin_files
        self.encoding = encoding
        self.permissions = permissions

        self.owner = owner
        self.group = group
        self.uid = None
        self.gid = None

        if owner is not None:
            self.uid, self.gid = command.get_user_info(owner)

        if group is not None:
            try:
                self.gid = grp.getgrnam(group).gr_gid
            except KeyError as error:
                raise errors.GroupNotFoundError(group) from error

    def copy_to(
        self,
        target_directory: str,
        variables: typing.Optional[dict[str, str]] = None,
        dry_run: bool = False,
    ) -> list[str]:
        """
        Copies the files in this directory to the target directory. Only replaces files that differ.

        Parameters:
            target_directory:
                Destination directory root. Relative layout from the source is preserved beneath
                this path.

            variables:
                Optional mapping of literal substrings to replace in text files before writing.
                Ignored for binary files.

            dry_run:
                If ``True``, perform a dry-run: no files are written, but the list of files that
                *would* be processed is returned.

        Returns:
            list[str]
                When ``dry_run`` is ``False``, paths of files that were created or whose contents
                were modified.

                When ``dry_run`` is ``True``, paths of all files that would be considered for
                creation or modification (no changes are actually performed).

        Raises:
            OSError
                If directory traversal or file I/O fails (e.g. permission denied).

            FileNotFoundError
                If ``source_directory`` does not exist or becomes unavailable.

            UnicodeDecodeError
                If a text file cannot be decoded using ``encoding``.

            UnicodeEncodeError
                If text content cannot be encoded using ``encoding``.
        """
        changed_or_created = []
        original_wd = os.getcwd()
        try:
            os.chdir(self.source_directory)
            for src_dir, _, src_files in os.walk("."):
                for src_file in src_files:
                    src_path = os.path.join(src_dir, src_file)
                    file = File(
                        source_file=src_path,
                        bin_file=self.bin_files,
                        encoding=self.encoding,
                        owner=self.owner,
                        group=self.group,
                        permissions=self.permissions,
                    )
                    target = os.path.normpath(os.path.join(target_directory, src_path))

                    if dry_run:
                        changed_or_created.append(target)
                    else:
                        if file.copy_to(target, variables):
                            changed_or_created.append(target)

        finally:
            os.chdir(original_wd)
        return changed_or_created
