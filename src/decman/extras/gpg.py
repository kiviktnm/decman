import os
import pwd
import re
import subprocess
from dataclasses import dataclass
from typing import Literal, Optional

import decman
import decman.core.module as module
import decman.core.output as output
import decman.core.store as _store
from decman.core.error import CommandFailedError

OwnerTrust = Literal["never", "marginal", "full", "ultimate"]
SourceKind = Literal["fingerprint", "uri", "file"]


_TRUST_MAP = {
    "never": "1",
    "marginal": "2",
    "full": "3",
    "ultimate": "4",
}

_FPR_RE = re.compile(r"^[0-9A-F]{40}$")


@dataclass(frozen=True)
class Key:
    fingerprint: str
    source_kind: SourceKind
    source: str  # keyserver / uri / filepath
    trust: Optional[OwnerTrust] = None

    def __post_init__(self) -> None:
        fpr = self.fingerprint.replace(" ", "").upper()
        if not _FPR_RE.fullmatch(fpr):
            raise ValueError(f"invalid OpenPGP fingerprint: {fpr}")
        object.__setattr__(self, "fingerprint", fpr)


class _GPGInterface:
    def __init__(self, user: str, home: str):
        self.user = user
        self.home = home

    def ensure_home(self) -> bool:
        """
        Returns True on succees. Returns False if the user doesn't exist.
        """

        def create_missing_dirs(dirct: str, uid: int, gid: int):
            dirct = os.path.normpath(dirct)
            if not os.path.isdir(dirct):
                parent_dir = os.path.dirname(dirct)
                if not os.path.isdir(parent_dir):
                    create_missing_dirs(parent_dir, uid, gid)

                os.mkdir(dirct)
                os.chown(dirct, uid, gid)
                os.chmod(dirct, 0o700)

        try:
            u = pwd.getpwnam(self.user)
            create_missing_dirs(self.home, u.pw_uid, u.pw_gid)
            return True
        except OSError as error:
            raise decman.SourceError(
                f"Failed to create GPG directory {self.home} for {self.user}."
            ) from error
        except KeyError:
            return False

    def list_fingerprints(self) -> set[str]:
        out = decman.prg(
            ["gpg", "--homedir", self.home, "--batch", "--no-tty", "--with-colons", "--list-keys"],
            user=self.user,
            pty=False,
        )
        fprs: set[str] = set()
        for line in out.splitlines():
            if line.startswith("fpr:"):
                parts = line.split(":")
                if len(parts) > 9 and parts[9]:
                    fprs.add(parts[9])
        return fprs

    def set_key_trust(self, keys: list[tuple[str, OwnerTrust]]):
        if not keys:
            return
        lines = [f"{fpr}:{_TRUST_MAP[trust]}:" for fpr, trust in keys]
        data = "\n".join(lines) + "\n"

        cmd = [
            "gpg",
            "--homedir",
            self.home,
            "--batch",
            "--yes",
            "--no-tty",
            "--import-ownertrust",
        ]
        p = subprocess.run(
            cmd,
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            user=self.user,
            text=True,
            check=False,
        )
        if p.returncode != 0:
            raise CommandFailedError(cmd, p.stdout)

    def delete_keys(self, fingerprints: list[str]):
        decman.prg(
            [
                "gpg",
                "--homedir",
                self.home,
                "--batch",
                "--yes",
                "--no-tty",
                "--delete-keys",
            ]
            + fingerprints,
            user=self.user,
            pty=False,
        )

    def fetch_key(self, uri: str):
        decman.prg(
            [
                "gpg",
                "--homedir",
                self.home,
                "--batch",
                "--yes",
                "--no-tty",
                "--fetch-key",
                uri,
            ],
            user=self.user,
            pty=False,
        )

    def import_key(self, path: str):
        decman.prg(
            [
                "gpg",
                "--homedir",
                self.home,
                "--batch",
                "--yes",
                "--no-tty",
                "--import",
                path,
            ],
            user=self.user,
            pty=False,
        )

    def receive_key(self, fingerprint: str, keyserver: str):
        decman.prg(
            [
                "gpg",
                "--homedir",
                self.home,
                "--batch",
                "--yes",
                "--no-tty",
                "--keyserver",
                keyserver,
                "--recv-keys",
                fingerprint,
            ],
            user=self.user,
            pty=False,
        )


class GPGReceiver(module.Module):
    """
    Module for receiving OpenPGP keys.

    This is basically built for importing AUR package keys.

    If trying to add a key to an user that doesn't exist, this module silently skips user.

    It's functionality is limited and I don't recommend using this with your main user account.
    Instead create specific account for AUR package building and import keys to that account.

    This module doesn't use the GPGME library and instead just calls gpg directly. It's simpler and
    good enough for this usecase.

    This module is a singleton, meaning that you should create only a one instance of this module
    and pass that around.
    """

    def __init__(self) -> None:
        super().__init__("gpgreceiver")
        self._keys: dict[tuple[str, str], list[Key]] = {}

    def receive_key(
        self,
        user: str,
        gpg_home: str,
        fingerprint: str,
        keyserver: str,
        trust: OwnerTrust | None = None,
    ):
        """
        Receives a key.

        The key is imported as the given ``user`` into the specified ``gpg_home``.

        If trust is specified, sets it.
        """
        self._keys.setdefault((user, gpg_home), []).append(
            Key(fingerprint, "fingerprint", keyserver, trust)
        )

    def fetch_key(
        self, user: str, gpg_home: str, fingerprint: str, uri: str, trust: OwnerTrust | None = None
    ):
        """
        Fetches a key from a URI.

        The key is imported as the given ``user`` into the specified ``gpg_home``.

        If trust is specified, sets it.
        """
        self._keys.setdefault((user, gpg_home), []).append(Key(fingerprint, "uri", uri, trust))

    def import_key(
        self, user: str, gpg_home: str, fingerprint: str, file: str, trust: OwnerTrust | None = None
    ):
        """
        Imports a key from file.

        The key is imported as the given ``user`` into the specified ``gpg_home``.

        If trust is specified, sets it.
        """
        self._keys.setdefault((user, gpg_home), []).append(Key(fingerprint, "file", file, trust))

    def _add_key(self, gpg: _GPGInterface, key: Key):
        match key.source_kind:
            case "fingerprint":
                gpg.receive_key(key.fingerprint, key.source)
            case "uri":
                gpg.fetch_key(key.source)
            case "file":
                gpg.import_key(key.source)

    def before_update(self, store: _store.Store):
        store.ensure("gpgreceiver_userhome_keys", {})

        known_users = {
            (line.split(":", 1)[0], line.split(":", 1)[1])
            for line in store["gpgreceiver_userhome_keys"]
        }

        for user, gpg_home in self._keys.keys() | known_users:
            keys = self._keys.get((user, gpg_home), [])
            gpg = _GPGInterface(user, gpg_home)

            if not gpg.ensure_home():
                output.print_warning(f"User {user} doesn't exist, so PGP keys cannot be modified.")
                del store["gpgreceiver_userhome_keys"][f"{user}:{gpg_home}"]
                continue

            old_fprs = store["gpgreceiver_userhome_keys"].get(f"{user}:{gpg_home}", set())
            fprs_before_import = gpg.list_fingerprints()
            new_fprs = set()
            managed_fprs = set()
            key_trust_levels = []

            for key in keys:
                managed_fprs.add(key.fingerprint)
                if key.trust:
                    key_trust_levels.append((key.fingerprint, key.trust))
                if key.fingerprint not in fprs_before_import:
                    output.print_info(
                        f"Adding PGP key {key.fingerprint} to {user}:{gpg_home} "
                        f"from {key.source_kind} {key.source}."
                    )
                    self._add_key(gpg, key)
                    new_fprs.add(key.fingerprint)

            fprs_after_import = gpg.list_fingerprints()
            missing = new_fprs - fprs_after_import
            if missing:
                raise decman.SourceError(
                    f"Fingerprints for PGP not found after importing all keys: {' '.join(missing)}"
                )

            if key_trust_levels:
                gpg.set_key_trust(key_trust_levels)

            unaccounted_fprs = (fprs_after_import - fprs_before_import) - new_fprs
            if unaccounted_fprs:
                output.print_warning(
                    "While adding PGP keys these fingerprints were unaccounted for: "
                    f"{' '.join(unaccounted_fprs)}"
                )
                output.print_warning("The keys were added, but their ownertrust was not set.")

            fprs_to_remove = list(old_fprs - managed_fprs)
            if fprs_to_remove:
                output.print_list(
                    f"Deleting PGP keys from {user}:{gpg_home}", fprs_to_remove, level=output.INFO
                )
                gpg.delete_keys(fprs_to_remove)

            store["gpgreceiver_userhome_keys"][f"{user}:{gpg_home}"] = managed_fprs
