import pyalpm
import pytest
from decman.plugins.aur import AurPacmanInterface
from decman.plugins.pacman import PacmanInterface


class FakePackage:
    def __init__(self, name: str, is_explicit: bool, required_by: list[str]):
        self.name = name
        self.reason = pyalpm.PKG_REASON_EXPLICIT if is_explicit else pyalpm.PKG_REASON_DEPEND
        self.required_by = required_by
        self.provides = [name]

    def compute_requiredby(self):
        return self.required_by


class FakeDB:
    def __init__(self, pkgcache: list[FakePackage]):
        self.pkgcache = pkgcache


class FakePyalpmHandle:
    def __init__(self):
        pass

    def get_syncdbs(self):
        return [
            FakeDB(
                [
                    FakePackage("a", True, []),
                    FakePackage("b", False, ["a"]),
                    FakePackage("c", False, ["b"]),
                    FakePackage("d", False, []),
                    FakePackage("e", False, ["f"]),
                    FakePackage("f", False, ["g"]),
                    FakePackage("g", False, []),
                ]
            )
        ]

    def get_localdb(self):
        return FakeDB(
            self.get_syncdbs()[0].pkgcache
            + [
                FakePackage("h", True, []),
                FakePackage("i", False, ["h"]),
                FakePackage("j", False, []),
                FakePackage("k", False, ["l"]),
                FakePackage("l", False, []),
            ]
        )


def fake_create_pyalpm_handle(self):
    return FakePyalpmHandle()


def test_get_native_orphans_pacman(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(PacmanInterface, "_create_pyalpm_handle", fake_create_pyalpm_handle)

    interface = PacmanInterface(
        None,  # type: ignore
        False,
        set(),
        2048,
        "/var/lib/pacman/",
    )

    assert interface.get_native_orphans() == {"d", "e", "f", "g"}


def test_get_foreign_orphans_aur(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(AurPacmanInterface, "_create_pyalpm_handle", fake_create_pyalpm_handle)

    interface = AurPacmanInterface(
        None,  # type: ignore
        False,
        set(),
        2048,
        "/var/lib/pacman/",
    )

    assert interface.get_foreign_orphans() == {"j", "k", "l"}
