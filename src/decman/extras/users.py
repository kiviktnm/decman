import grp
import pwd
from dataclasses import dataclass
from typing import Optional

import decman.core.command as command
import decman.core.module as module
import decman.core.output as output
import decman.core.store as _store


@dataclass(frozen=True)
class Group:
    """
    Represents a group managed by the ``UserManager`` module.

    The ``system`` attribute only affects the creation of this group.
    After the group has been created, changing the ``system`` attribute does nothing.
    """

    groupname: str
    gid: Optional[int] = None
    system: bool = False

    def __str__(self) -> str:
        parts = []
        if self.gid is not None:
            parts.append(f"gid={self.gid}")
        if self.system:
            parts.append("system")
        return f"{self.groupname}({', '.join(parts)})"


@dataclass(frozen=True)
class User:
    """
    Represents a user managed by the ``UserManager`` module.

    The ``system`` attribute only affects the creation of this user.
    After the user has been created, changing the ``system`` attribute does nothing.
    """

    username: str
    uid: Optional[int] = None
    group: Optional[str] = None
    home: Optional[str] = None
    shell: Optional[str] = None
    groups: tuple[str, ...] = ()
    system: bool = False

    def __str__(self) -> str:
        parts = []
        if self.uid is not None:
            parts.append(f"uid={self.uid}")
        if self.group is not None:
            parts.append(f"gid={self.group}")
        if self.home is not None:
            parts.append(f"home={self.home}")
        if self.shell is not None:
            parts.append(f"shell={self.shell}")
        if self.groups:
            parts.append(f"groups={','.join(self.groups)}")
        if self.system:
            parts.append("system")
        return f"{self.username}({', '.join(parts)})"


class UserManager(module.Module):
    """
    A module for managing users and groups. This module is additive, if you create a user or a group
    manually, this module will not modify them, unless you explicitly add them to this module.

    Users and groups are created, modified and deleted at ``before_update`` -stage.
    Users are added to groups and subuids/subgids at ``after_update`` -stage.

    Decman store keys used by this module are:

        - ``usermanager_users``
        - ``usermanager_groups``
        - ``usermanager_user_additional_groups``
        - ``usermanager_user_subuids``
        - ``usermanager_user_subgids``

    Most management done by this module is with the commands ``useradd``, ``groupadd`` and
    ``usermod``.

    This module contains useful utilities for the most common user management cases,
    but it is not complete.
    If you need advanced user management features you should probably fork this module.

    This module is a singleton, meaning that you should create only a one instance of this module
    and pass that around.
    """

    def __init__(self) -> None:
        super().__init__("usermanager")
        self.users: set[User] = set()
        self.groups: set[Group] = set()
        self._user_additional_groups: dict[str, set[str]] = {}
        self._user_subuids: dict[str, set[tuple[int, int]]] = {}
        self._user_subgids: dict[str, set[tuple[int, int]]] = {}

    def add_user(self, user: User):
        """
        Ensures that the user exists with the given attributes.
        """
        self.users.add(user)

    def add_group(self, group: Group):
        """
        Ensures that the group exists with the given attributes.
        """
        self.groups.add(group)

    def add_user_to_group(self, user: str, group: str):
        """
        Ensures that the user is a member of the given group.

        Both ``user`` and ``group`` should exist.
        """
        self._user_additional_groups.setdefault(user, set()).add(group)

    def add_subuids(self, user: str, first: int, last: int):
        """
        Adds the range ``first``-``last`` subordinate uids to the ``user``s account.

        Note!

            This module doesn't parse ``/etc/subuid`` or ``/etc/subgid``.
            Instead, the added subuids and subgids are stored in the decman store.
            Stored values are used to remove the added subuids and subgids from the user.

            Manual modifications or clearing the decman store can cause unexpected issues.
        """
        self._user_subuids.setdefault(user, set()).add((first, last))

    def add_subgids(self, user: str, first: int, last: int):
        """
        Adds the range ``first``-``last`` subordinate gids to the ``user``s account.

        Note!

            This module doesn't parse ``/etc/subuid`` or ``/etc/subgid``.
            Instead, the added subuids and subgids are stored in the decman store.
            Stored values are used to remove the added subuids and subgids from the user.

            Manual modifications or clearing the decman store can cause unexpected issues.
        """
        self._user_subgids.setdefault(user, set()).add((first, last))

    def _check_user(self, user: User, user_groups_index: dict[str, set[str]]):
        userdb_name = None
        userdb_uid = None

        try:
            userdb_name = pwd.getpwnam(user.username)
        except KeyError:
            pass

        try:
            if user.uid is not None:
                userdb_uid = pwd.getpwuid(user.uid)
        except KeyError:
            pass

        # Prioritize uid match. If uid matches but name doesn't, rename the user.
        userdb = userdb_uid or userdb_name

        if not userdb:
            self._add_user(user)
        else:
            self._ensure_user_matches(user, userdb, user_groups_index)

    def _add_user(self, user: User):
        cmd = ["useradd"]

        if user.uid is not None:
            cmd += ["--uid", str(user.uid)]

        if user.group:
            cmd += ["--gid", user.group]

        if user.home:
            cmd += ["--create-home", "--home-dir", user.home]

        if user.shell:
            cmd += ["--shell", user.shell]

        if user.groups:
            cmd += ["--groups", ",".join(list(user.groups))]

        if user.system:
            cmd.append("--system")

        cmd.append(user.username)
        output.print_info(f"Creating user {user}.")
        command.prg(cmd, pty=False)

    def _ensure_user_matches(
        self, user: User, userdb: pwd.struct_passwd, user_groups_index: dict[str, set[str]]
    ):
        cmd = ["usermod"]

        if user.username != userdb.pw_name:
            cmd += ["--login", user.username]

        if user.uid is not None and user.uid != userdb.pw_uid:
            cmd += ["--uid", str(user.uid)]

        if user.group and user.group != grp.getgrgid(userdb.pw_gid).gr_name:
            cmd += ["--gid", user.group]

        if user.home and user.home != userdb.pw_dir:
            cmd += ["--move-home", "--home", user.home]

        if user.shell and user.shell != userdb.pw_shell:
            cmd += ["--shell", user.shell]

        # Use old name to support renames, post rename groups match
        old_groups = user_groups_index.get(userdb.pw_name, set())
        if user.groups is not None and set(user.groups) != old_groups:
            if user.groups:
                cmd += ["--groups", ",".join(list(user.groups))]
            elif old_groups:
                # Remove user from other groups
                cmd += ["-r", "--groups", ",".join(old_groups)]

        if len(cmd) > 1:
            # Use old name to support renames
            cmd.append(userdb.pw_name)
            output.print_info(f"Modifying user {user}.")
            command.prg(cmd, pty=False)

    def _user_groups_index(self) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {}
        for gr in grp.getgrall():
            group = gr.gr_name
            for user in gr.gr_mem:
                result.setdefault(user, set()).add(group)
        return result

    def _check_group(self, group: Group):
        groupdb_name = None
        groupdb_gid = None

        try:
            groupdb_name = grp.getgrnam(group.groupname)
        except KeyError:
            pass

        try:
            if group.gid is not None:
                groupdb_gid = grp.getgrgid(group.gid)
        except KeyError:
            pass

        groupdb = groupdb_gid or groupdb_name

        if not groupdb:
            self._add_group(group)
        else:
            self._ensure_group_matches(group, groupdb)

    def _add_group(self, group: Group):
        cmd = ["groupadd"]

        if group.gid is not None:
            cmd += ["--gid", str(group.gid)]

        if group.system:
            cmd.append("--system")

        cmd.append(group.groupname)
        output.print_info(f"Creating group {group}.")
        command.prg(cmd, pty=False)

    def _ensure_group_matches(self, group: Group, groupdb: grp.struct_group):
        cmd = ["groupmod"]

        if group.groupname != groupdb.gr_name:
            cmd += ["--new-name", group.groupname]

        if group.gid is not None and group.gid != groupdb.gr_gid:
            cmd += ["--gid", str(group.gid)]

        if len(cmd) > 1:
            # Use old name to support renames
            cmd.append(groupdb.gr_name)
            output.print_info(f"Modifying group {group}.")
            command.prg(cmd, pty=False)

    def _modify_user_groups_subids(self, user: str, store: _store.Store):
        store.ensure("usermanager_user_additional_groups", {})
        store.ensure("usermanager_user_subuids", {})
        store.ensure("usermanager_user_subgids", {})

        old_groups = store["usermanager_user_additional_groups"].get(user, set())
        old_subuids = store["usermanager_user_subuids"].get(user, set())
        old_subgids = store["usermanager_user_subgids"].get(user, set())

        new_groups = self._user_additional_groups.get(user, set())
        new_subuids = self._user_subuids.get(user, set())
        new_subgids = self._user_subgids.get(user, set())

        groups_to_remove = old_groups - new_groups
        groups_to_add = new_groups - old_groups
        subuids_to_remove = old_subuids - new_subuids
        subuids_to_add = new_subuids - old_subuids
        subgids_to_remove = old_subgids - new_subgids
        subgids_to_add = new_subgids - old_subgids

        output.print_list(
            f"Removing {user} from groups:", list(groups_to_remove), level=output.INFO
        )
        output.print_list(f"Adding {user} to groups:", list(groups_to_add), level=output.INFO)

        # It's not possible to remove and add groups at the same time, so remove groups first
        if groups_to_remove:
            command.prg(["usermod", "-r", "-G", ",".join(groups_to_remove), user], pty=False)
            # Set these only if things change, no need to clutter the store otherwise
            store["usermanager_user_additional_groups"][user] = new_groups

        # Rest of the changes can be done with a single command
        cmd = ["usermod"]
        if groups_to_add:
            cmd += ["-a", "-G", ",".join(groups_to_add)]

        for first, last in subuids_to_remove:
            output.print_info(f"Removing subuids {first}-{last} from {user}.")
            cmd += ["--del-subuids", f"{first}-{last}"]

        for first, last in subuids_to_add:
            output.print_info(f"Adding subuids {first}-{last} to {user}.")
            cmd += ["--add-subuids", f"{first}-{last}"]

        for first, last in subgids_to_remove:
            output.print_info(f"Removing subgids {first}-{last} from {user}.")
            cmd += ["--del-subgids", f"{first}-{last}"]

        for first, last in subgids_to_add:
            output.print_info(f"Adding subgids {first}-{last} to {user}.")
            cmd += ["--add-subgids", f"{first}-{last}"]

        if len(cmd) > 1:
            cmd.append(user)
            command.prg(cmd, pty=False)

            # Set these only if things change, no need to clutter the store otherwise
            store["usermanager_user_additional_groups"][user] = new_groups
            store["usermanager_user_subuids"][user] = new_subuids
            store["usermanager_user_subgids"][user] = new_subgids

    def _delete_users_and_groups(self, store: _store.Store):
        store.ensure("usermanager_users", set())
        store.ensure("usermanager_groups", set())

        managed_users = set(map(lambda u: u.username, self.users))
        managed_groups = set(map(lambda g: g.groupname, self.groups))

        groups_to_remove = store["usermanager_groups"] - managed_groups
        users_to_remove = store["usermanager_users"] - managed_users

        for user in users_to_remove:
            output.print_info(f"Deleting user {user}.")
            command.prg(["userdel", user], pty=False)

        store["usermanager_users"] = managed_users

        for group in groups_to_remove:
            output.print_info(f"Deleting group {group}.")
            command.prg(["groupdel", group], pty=False)

        store["usermanager_groups"] = managed_groups

    def before_update(self, store: _store.Store):
        for group in self.groups:
            self._check_group(group)
        user_groups_index = self._user_groups_index()
        for user in self.users:
            self._check_user(user, user_groups_index)

        self._delete_users_and_groups(store)

    def after_update(self, store: _store.Store):
        # Iterate all entries to ensure removals take place
        for user in pwd.getpwall():
            self._modify_user_groups_subids(user.pw_name, store)
