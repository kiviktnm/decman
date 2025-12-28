# Extras

Decman ships with some built in modules. They implement functionality that is probably useful for declarative management, but for one reason or another don't make sense as plugins.

## User and group management module

```python
import decman.extras.users
```

A decman module for managing system users, groups, and supplementary group membership and subordinate UID/GID ranges for existing users.

The module is **additive**: it only manages users/groups you explicitly register, and it only manages additional groups/subids you explicitly define. Anything created manually and not tracked by this module is left alone.

### Provided types

#### `Group`

Represents a managed group.

```python
@dataclass(frozen=True)
class Group:
    groupname: str
    gid: Optional[int] = None
    system: bool = False
```

Fields:

- `groupname`: Group name.
- `gid`: Desired numeric GID. If omitted, system assigns one.
- `system`: Only affects _creation_ (`groupadd --system`). Changing this after creation does nothing.

#### `User`

Represents a managed user.

```python
@dataclass(frozen=True)
class User:
    username: str
    uid: Optional[int] = None
    group: Optional[str] = None
    home: Optional[str] = None
    shell: Optional[str] = None
    groups: tuple[str, ...] = ()
    system: bool = False
```

Fields:

- `username`: Login name.
- `uid`: Desired numeric UID. If omitted, system assigns one.
- `group`: Primary group name.
- `home`: Home directory.
- `shell`: Login shell.
- `groups`: Supplementary groups set.
- `system`: Only affects _creation_ (`useradd --system`). Changing this after creation does nothing.

### `UserManager` module

```python
class UserManager(Module):
```

#### Lifecycle

- Before update
  - Create/modify managed groups.
  - Create/modify managed users.
  - Delete previously-managed users/groups that are no longer listed.
- After update
  - Apply **additional** supplementary group membership and **subuid/subgid** ranges (including removals).

#### Store keys

The module persists state in decman store under these keys:

- `usermanager_users`
- `usermanager_groups`
- `usermanager_user_additional_groups`
- `usermanager_user_subuids`
- `usermanager_user_subgids`

The module does **not** parse `/etc/subuid` or `/etc/subgid`; it relies on these store keys to compute additions/removals.

#### Methods

##### `add_user(user: User)`

Ensure a user exists with the configured attributes.

Notes:

- If `uid` is provided and an existing user matches by UID but has a different name, the module will rename the user (`usermod --login`) and apply other changes.

##### `add_group(group: Group)`

Ensure a group exists with the configured attributes.

##### `add_user_to_group(user: str, group: str)`

Ensure `user` is a member of `group`.

- This is applied in `after_update`.
- Both `user` and `group` are expected to exist

You should not use this method for users added with `add_user`.

##### `add_subuids(user: str, first: int, last: int)`

Ensure subordinate UID range `first-last` is present for `user`.

##### `add_subgids(user: str, first: int, last: int)`

Ensure subordinate GID range `first-last` is present for `user`.

### Example usage

```python
from decman.extras.users import UserManager, User, Group

um = UserManager()

um.add_group(Group("containers", system=True))
um.add_user(User(
    username="alice",
    uid=1001,
    group="users",
    home="/home/alice",
    groups=(),
    shell="/bin/zsh",
))

um.add_user_to_group("bob", "containers")

um.add_subuids("alice", 100000, 165535)
um.add_subgids("alice", 100000, 165535)

import decman
decman.modules += [um]
```

## GPG receiver module

```python
import decman.extras.gpg
```

Manages importing OpenPGP public keys into per-user GnuPG homes. Tracks imported keys in the decman store and removes keys that were previously managed but are no longer configured.

This module is intentionally limited since it's main usage is for AUR build users. You probably shouldn't manage your primary user’s keyring with it.

### Types

#### `OwnerTrust`

Valid ownertrust levels:

- `never`
- `marginal`
- `full`
- `ultimate`

These map to GnuPG `--import-ownertrust` numeric levels `1..4`.

#### `SourceKind`

How a key is imported:

- `fingerprint`: fetch from keyserver via `--recv-keys`
- `uri`: fetch from URI via `--fetch-key`
- `file`: import from local file via `--import`

#### `Key`

Represents one managed key entry.

Fields:

- `fingerprint`: OpenPGP fingerprint, validated to be exactly 40 hex chars (spaces allowed in input; normalized by removing spaces and uppercasing).
- `source_kind`: one of `fingerprint | uri | file`.
- `source`: keyserver (for `fingerprint`), URI (for `uri`), or filepath (for `file`).
- `trust`: optional `OwnerTrust` to set via ownertrust import.

Validation behavior:

- Fingerprint is normalized: `replace(" ", "").upper()`.
- Fingerprint must match `^[0-9A-F]{40}$`; otherwise `ValueError`.

### `GPGReceiver` module

```python
class GPGReceiver(module.Module):
```

#### Store keys

The module persists state in decman store under these keys:

- `gpgreceiver_userhome_keys`

It relies on the store to keep track which keys were added by it.

#### Public API

##### `receive_key(user: str, gpg_home: str, fingerprint: str, keyserver: str, trust: OwnerTrust | None = None)`

Receives a key with a `fingerprint` from a `keyserver` to a `gpg_home` owned by `user`.

If `trust` is provided, ownertrust is set after import.

##### `fetch_key(user: str, gpg_home: str, fingerprint: str, uri: str, trust: OwnerTrust | None=None)`

Receives a key with a `fingerprint` from a `uri` to a `gpg_home` owned by `user`.

If `trust` is provided, ownertrust is set after import.

##### `import_key(user: str, gpg_home: str, fingerprint: str, file: str, trust: OwnerTrust | None =None)`

Receives a key with a `fingerprint` from a local `file` to a `gpg_home` owned by `user`.

If `trust` is provided, ownertrust is set after import.

### Example usage

```python
from decman.modules.gpg import GPGReceiver
import decman

gpg = GPGReceiver()

# Receive a key from a keyserver
gpg.receive_key(
    user="builduser",
    gpg_home="/var/lib/builduser/gnupg",
    fingerprint="AAAA AAAA AAAA AAAA AAAA AAAA AAAA AAAA AAAA AAAA",
    keyserver="hkps://keyserver.ubuntu.com",
    trust="marginal",
)

# Fetch a key from a URI
gpg.fetch_key(
    user="alice",
    gpg_home="/home/alice/.gnupg",
    fingerprint="BBBB BBBB BBBB BBBB BBBB BBBB BBBB BBBB BBBB BBBB",
    uri="https://example.org/signing-key.asc",
)

# Import a key from a local file
gpg.import_key(
    user="bob",
    gpg_home="/home/bob/.gnupg",
    fingerprint="CCCC CCCC CCCC CCCC CCCC CCCC CCCC CCCC CCCC CCCC",
    file="/etc/decman/keys/custom.asc",
)

decman.modules += [gpg]
```
