import pathlib

import pytest
from decman.plugins.aur import package as pkg_mod
from decman.plugins.aur.error import AurRPCError, PKGBUILDParseError
from decman.plugins.aur.package import (
    CustomPackage,
    PackageInfo,
    PackageSearch,
)


@pytest.fixture(autouse=True)
def silence_output(monkeypatch):
    # Avoid real I/O / prompts in tests by default
    monkeypatch.setattr(pkg_mod.output, "print_debug", lambda *a, **k: None)
    monkeypatch.setattr(pkg_mod.output, "print_summary", lambda *a, **k: None)
    monkeypatch.setattr(
        pkg_mod.output,
        "prompt_number",
        lambda *a, **k: 1,  # safe default
    )


# --- PackageInfo -----------------------------------------------------------


def test_packageinfo_requires_exactly_one_source():
    with pytest.raises(ValueError, match="cannot be None"):
        PackageInfo(pkgname="a", pkgbase="a", version="1.0")

    with pytest.raises(ValueError, match="cannot be set"):
        PackageInfo(
            pkgname="a",
            pkgbase="a",
            version="1.0",
            git_url="git://example",
            pkgbuild_directory="/tmp",
        )


class DummyPacman:
    def __init__(self, installable: set[str]):
        self._installable = installable
        self.calls: list[str] = []

    def is_installable(self, name: str) -> bool:
        self.calls.append(name)
        return name in self._installable


def _make_pkg_for_deps() -> PackageInfo:
    return PackageInfo(
        pkgname="pkg",
        pkgbase="pkg",
        version="1.0",
        git_url="git://example",
        dependencies=("native>=1", "foreign=2"),
        make_dependencies=("make-native", "make-foreign>=3"),
        check_dependencies=("check-foreign<4", "check-native"),
    )


def test_packageinfo_foreign_and_native_dependencies_are_split_and_stripped():
    pacman = DummyPacman(
        {
            "native>=1",
            "make-native",
            "check-native",
        }
    )
    pkg = _make_pkg_for_deps()

    assert pkg.native_dependencies(pacman) == ["native"]
    assert pkg.foreign_dependencies(pacman) == ["foreign"]
    assert pkg.native_make_dependencies(pacman) == ["make-native"]
    assert pkg.foreign_make_dependencies(pacman) == ["make-foreign"]
    assert pkg.native_check_dependencies(pacman) == ["check-native"]
    assert pkg.foreign_check_dependencies(pacman) == ["check-foreign"]


# --- CustomPackage ---------------------------------------------------------


def test_custompackage_requires_exactly_one_source():
    with pytest.raises(ValueError, match="cannot be None"):
        CustomPackage("pkg", git_url=None, pkgbuild_directory=None)

    with pytest.raises(ValueError, match="cannot be set"):
        CustomPackage("pkg", git_url="git://example", pkgbuild_directory="/tmp")


class DummyCommands:
    """Minimal stub; only here so type checks pass where needed."""

    pass


@pytest.mark.parametrize(
    "srcinfo, expected_version",
    [
        (
            """
            pkgbase = foo
                pkgver = 1.2.3
                pkgrel = 4
            pkgname = foo
            """,
            "1.2.3-4",
        ),
        (
            """
            pkgbase = foo
                pkgver = 1.2.3
                pkgrel = 4
                epoch = 2
            pkgname = foo
            """,
            "2:1.2.3-4",
        ),
        (
            """
            pkgbase = foo
                pkgver = 1.2.3
            pkgname = foo
            """,
            "1.2.3",
        ),
    ],
)
def test_parse_srcinfo_version_handling(srcinfo: str, expected_version: str) -> None:
    pkg = CustomPackage(pkgname="foo", git_url=None, pkgbuild_directory="/dummy")

    info = pkg._parse_srcinfo(srcinfo)

    assert info.pkgname == "foo"
    assert info.pkgbase == "foo"
    assert info.version == expected_version


def test_parse_srcinfo_single_package_dependencies() -> None:
    srcinfo = """
    pkgbase = foo
        pkgver = 1.2.3
        pkgrel = 1
        depends = bar>=1.0
        makedepends = baz
        checkdepends = qux

    pkgname = foo
    """

    pkg = CustomPackage(pkgname="foo", git_url=None, pkgbuild_directory="/dummy")

    info = pkg._parse_srcinfo(srcinfo)

    assert info.dependencies == ("bar>=1.0",)
    assert info.make_dependencies == ("baz",)
    assert info.check_dependencies == ("qux",)


def test_parse_srcinfo_split_package_uses_only_target_pkg_dependencies(monkeypatch) -> None:
    # Ensure arch-specific keys match
    monkeypatch.setattr(pkg_mod.config, "arch", "x86_64", raising=False)

    srcinfo = """
    pkgbase = clion
        pkgver = 2025.3
        pkgrel = 1
        makedepends = rsync
        depends = base-dep
        depends_x86_64 = base-arch-dep

    pkgname = clion
        depends = libdbusmenu-glib
        depends_x86_64 = clion-arch-dep
        checkdepends = clion-check

    pkgname = clion-jre
        depends = jre-dep
        makedepends = jre-make

    pkgname = clion-cmake
        depends = cmake-dep
    """

    pkg = CustomPackage(pkgname="clion", git_url=None, pkgbuild_directory="/dummy")

    info = pkg._parse_srcinfo(srcinfo)

    # version
    assert info.pkgbase == "clion"
    assert info.version == "2025.3-1"

    # base deps + target pkg deps (including arch-specific)
    assert info.dependencies == (
        "base-dep",
        "base-arch-dep",
        "libdbusmenu-glib",
        "clion-arch-dep",
    )

    # only base and target pkg makedepends
    assert info.make_dependencies == ("rsync",)

    # base + target pkg checkdepends
    assert info.check_dependencies == ("clion-check",)


def test_parse_srcinfo_arch_specific_ignored_for_other_arch(monkeypatch) -> None:
    # Different arch → *_x86_64 keys should be ignored
    monkeypatch.setattr(pkg_mod.config, "arch", "aarch64", raising=False)

    srcinfo = """
    pkgbase = foo
        pkgver = 1.0
        pkgrel = 1
        depends_x86_64 = base-arch-dep

    pkgname = foo
        depends = common-dep
        depends_x86_64 = pkg-arch-dep
    """

    pkg = CustomPackage(pkgname="foo", git_url=None, pkgbuild_directory="/dummy")

    info = pkg._parse_srcinfo(srcinfo)

    # Only common deps, no *_x86_64 because arch != x86_64
    assert info.dependencies == ("common-dep",)


def test_parse_srcinfo_missing_required_fields_raises() -> None:
    # Missing pkgbase
    srcinfo_no_pkgbase = """
        pkgver = 1.0
        pkgrel = 1
        pkgname = foo
    """
    pkg = CustomPackage(pkgname="foo", git_url=None, pkgbuild_directory="/dummy")

    with pytest.raises(PKGBUILDParseError) as excinfo:
        pkg._parse_srcinfo(srcinfo_no_pkgbase)
    assert "pkgbase/pkgver" in str(excinfo.value)

    # Missing pkgver
    srcinfo_no_pkgver = """
        pkgbase = foo
        pkgname = foo
    """

    with pytest.raises(PKGBUILDParseError) as excinfo2:
        pkg._parse_srcinfo(srcinfo_no_pkgver)
    assert "pkgbase/pkgver" in str(excinfo2.value)


def test_parse_srcinfo_missing_target_pkg_raises() -> None:
    srcinfo = """
    pkgbase = foo
        pkgver = 1.0
        pkgrel = 1
    pkgname = other
    """

    pkg = CustomPackage(pkgname="foo", git_url=None, pkgbuild_directory="/dummy")

    with pytest.raises(PKGBUILDParseError) as excinfo:
        pkg._parse_srcinfo(srcinfo)

    msg = str(excinfo.value)
    assert "Package foo not found in SRCINFO" in msg
    assert "other" in msg  # listed in present packages


def test_srcinfo_from_pkgbuild_directory_missing_dir_raises(tmp_path: pathlib.Path) -> None:
    missing = tmp_path / "does-not-exist"

    pkg = CustomPackage(pkgname="foo", git_url=None, pkgbuild_directory=str(missing))

    with pytest.raises(PKGBUILDParseError) as excinfo:
        pkg._srcinfo_from_pkgbuild_directory(DummyCommands())

    msg = str(excinfo.value)
    assert "does not exist or is not a directory" in msg


def test_srcinfo_from_pkgbuild_directory_missing_pkgbuild_raises(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "pkgdir"
    path.mkdir()

    pkg = CustomPackage(pkgname="foo", git_url=None, pkgbuild_directory=str(path))

    with pytest.raises(PKGBUILDParseError) as excinfo:
        pkg._srcinfo_from_pkgbuild_directory(DummyCommands())

    msg = str(excinfo.value)
    assert "No PKGBUILD found" in msg


def test_custom_package_equality_and_hash() -> None:
    a1 = CustomPackage(
        pkgname="foo", git_url="https://example.com/repo.git", pkgbuild_directory=None
    )
    a2 = CustomPackage(
        pkgname="foo", git_url="https://example.com/repo.git", pkgbuild_directory=None
    )
    b = CustomPackage(pkgname="foo", git_url=None, pkgbuild_directory="/some/path")

    assert a1 == a2
    assert hash(a1) == hash(a2)

    assert a1 != b
    assert hash(a1) != hash(b)


def test_custom_package_str_git_and_directory() -> None:
    git_pkg = CustomPackage(
        pkgname="foo",
        git_url="https://example.com/repo.git",
        pkgbuild_directory=None,
    )
    dir_pkg = CustomPackage(
        pkgname="foo",
        git_url=None,
        pkgbuild_directory="/some/path",
    )

    assert "pkgname=foo" in str(git_pkg)
    assert "git_url=https://example.com/repo.git" in str(git_pkg)

    assert "pkgname=foo" in str(dir_pkg)
    assert "pkgbuild_directory=/some/path" in str(dir_pkg)


# --- PackageSearch: caching ------------------------------------------------


def _make_pkg(name: str = "pkg") -> PackageInfo:
    return PackageInfo(
        pkgname=name,
        pkgbase=name,
        version="1.0",
        git_url=f"git://example/{name}",
        provides=("virt-" + name,),
        dependencies=("dep",),
        make_dependencies=(),
        check_dependencies=(),
    )


def test_add_custom_pkg_caches_package():
    search = PackageSearch()
    pkg = _make_pkg("foo")

    search.add_custom_pkg(pkg)

    assert pkg in search._custom_packages
    assert search._package_cache["foo"] is pkg
    assert search._all_providers_cache["virt-foo"] == ["foo"]


def test_try_caching_packages_skips_already_cached(monkeypatch):
    search = PackageSearch()
    pkg = _make_pkg("foo")
    search._cache_pkg(pkg)

    calls = []

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("requests.get should not be called")

    monkeypatch.setattr(pkg_mod.requests, "get", fake_get)

    search.try_caching_packages(["foo"])
    assert calls == []


def test_try_caching_packages_caches_from_aur(monkeypatch):
    search = PackageSearch()

    def fake_get(url, timeout):
        class Resp:
            def json(self):
                return {
                    "type": "success",
                    "results": [
                        {
                            "Name": "bar",
                            "PackageBase": "bar-base",
                            "Version": "2.0",
                            "Depends": ["dep1"],
                            "MakeDepends": ["make1"],
                            "CheckDepends": ["check1"],
                            "Provides": ["virt-bar"],
                        }
                    ],
                }

        return Resp()

    monkeypatch.setattr(pkg_mod.requests, "get", fake_get)

    search.try_caching_packages(["bar"])

    assert "bar" in search._package_cache
    info = search._package_cache["bar"]
    assert isinstance(info, PackageInfo)
    assert search._all_providers_cache["virt-bar"] == ["bar"]


def test_try_caching_packages_aur_returns_error(monkeypatch):
    search = PackageSearch()

    def fake_get(url, timeout):
        class Resp:
            def json(self):
                return {"type": "error", "error": "boom"}

        return Resp()

    monkeypatch.setattr(pkg_mod.requests, "get", fake_get)

    with pytest.raises(AurRPCError):
        search.try_caching_packages(["bar"])


def test_try_caching_packages_request_exception_raises_aur_error(monkeypatch):
    search = PackageSearch()

    class DummyError(pkg_mod.requests.RequestException):
        pass

    def fake_get(url, timeout):
        raise DummyError("boom")

    monkeypatch.setattr(pkg_mod.requests, "get", fake_get)

    with pytest.raises(AurRPCError):
        search.try_caching_packages(["bar"])


# --- PackageSearch: get_package_info --------------------------------------


def test_get_package_info_returns_from_cache():
    search = PackageSearch()
    pkg = _make_pkg("foo")
    search._cache_pkg(pkg)

    result = search.get_package_info("foo")
    assert result is pkg


def test_get_package_info_returns_custom_package_if_not_cached():
    search = PackageSearch()
    pkg = _make_pkg("foo")
    search._custom_packages.append(pkg)

    result = search.get_package_info("foo")

    assert result is pkg
    assert search._package_cache["foo"] is pkg


def test_get_package_info_aur_not_found_returns_none(monkeypatch):
    search = PackageSearch()

    def fake_get(url, timeout):
        class Resp:
            def json(self):
                return {"type": "success", "resultcount": 0, "results": []}

        return Resp()

    monkeypatch.setattr(pkg_mod.requests, "get", fake_get)

    result = search.get_package_info("foo")
    assert result is None
    assert "foo" not in search._package_cache


def test_get_package_info_aur_success_caches_and_returns(monkeypatch):
    search = PackageSearch()

    def fake_get(url, timeout):
        class Resp:
            def json(self):
                return {
                    "type": "success",
                    "resultcount": 1,
                    "results": [
                        {
                            "Name": "foo",
                            "PackageBase": "foo-base",
                            "Version": "1.2",
                            "Depends": ["dep1"],
                            "MakeDepends": ["make1"],
                            "CheckDepends": ["check1"],
                            "Provides": ["virt-foo"],
                        }
                    ],
                }

        return Resp()

    monkeypatch.setattr(pkg_mod.requests, "get", fake_get)

    result = search.get_package_info("foo")
    assert isinstance(result, PackageInfo)
    assert result.pkgname == "foo"
    assert search._package_cache["foo"] is result


def test_get_package_info_aur_returns_error(monkeypatch):
    search = PackageSearch()

    def fake_get(url, timeout):
        class Resp:
            def json(self):
                return {"type": "error", "error": "boom"}

        return Resp()

    monkeypatch.setattr(pkg_mod.requests, "get", fake_get)

    with pytest.raises(AurRPCError):
        search.get_package_info("foo")


def test_get_package_info_request_exception_raises_aur_error(monkeypatch):
    search = PackageSearch()

    class DummyError(pkg_mod.requests.RequestException):
        pass

    def fake_get(url, timeout):
        raise DummyError("boom")

    monkeypatch.setattr(pkg_mod.requests, "get", fake_get)

    with pytest.raises(AurRPCError):
        search.get_package_info("foo")


# --- PackageSearch: find_provider -----------------------------------------


def test_find_provider_uses_selected_providers_cache():
    search = PackageSearch()
    pkg = _make_pkg("foo")
    search._selected_providers_cache["dep"] = pkg

    result = search.find_provider("dep")
    assert result is pkg


def test_find_provider_exact_name_match(monkeypatch):
    search = PackageSearch()
    pkg = _make_pkg("dep")

    def fake_get_package_info(name: str):
        assert name == "dep"
        return pkg

    monkeypatch.setattr(search, "get_package_info", fake_get_package_info)

    result = search.find_provider("dep")
    assert result is pkg
    assert search._selected_providers_cache["dep"] is pkg


def test_find_provider_single_known_provider(monkeypatch):
    search = PackageSearch()
    pkg = _make_pkg("provider")
    search._all_providers_cache["dep"] = ["provider"]

    def fake_get_package_info(name: str):
        if name == "dep":
            return None
        assert name == "provider"
        return pkg

    monkeypatch.setattr(search, "get_package_info", fake_get_package_info)

    result = search.find_provider("dep")
    assert result is pkg
    assert search._selected_providers_cache["dep"] is pkg


def test_find_provider_aur_search_not_found(monkeypatch):
    search = PackageSearch()

    def fake_get_package_info(name: str):
        # Exact name match should fail
        return None

    monkeypatch.setattr(search, "get_package_info", fake_get_package_info)

    def fake_get(url, timeout):
        class Resp:
            def json(self):
                return {"type": "success", "resultcount": 0, "results": []}

        return Resp()

    monkeypatch.setattr(pkg_mod.requests, "get", fake_get)

    result = search.find_provider("dep")
    assert result is None


def test_find_provider_aur_search_single_result(monkeypatch):
    search = PackageSearch()
    pkg = _make_pkg("provider")

    def fake_get_package_info(name: str):
        # first call for stripped_dependency -> None
        if name == "dep":
            return None
        assert name == "provider"
        return pkg

    monkeypatch.setattr(search, "get_package_info", fake_get_package_info)

    def fake_get(url, timeout):
        class Resp:
            def json(self):
                return {
                    "type": "success",
                    "resultcount": 1,
                    "results": [{"Name": "provider"}],
                }

        return Resp()

    monkeypatch.setattr(pkg_mod.requests, "get", fake_get)

    result = search.find_provider("dep")
    assert result is pkg


def test_find_provider_aur_search_multiple_results_calls_choose_provider(monkeypatch):
    search = PackageSearch()

    def fake_get_package_info(name: str):
        # no exact match
        return None

    monkeypatch.setattr(search, "get_package_info", fake_get_package_info)

    def fake_get(url, timeout):
        class Resp:
            def json(self):
                return {
                    "type": "success",
                    "resultcount": 2,
                    "results": [{"Name": "a"}, {"Name": "b"}],
                }

        return Resp()

    monkeypatch.setattr(pkg_mod.requests, "get", fake_get)

    sentinel = object()

    def fake_choose(dep, providers, where):
        assert dep == "dep"
        assert providers == ["a", "b"]
        assert where == "AUR"
        return sentinel

    monkeypatch.setattr(search, "_choose_provider", fake_choose)

    result = search.find_provider("dep")
    assert result is sentinel


def test_find_provider_aur_search_error(monkeypatch):
    search = PackageSearch()

    def fake_get_package_info(name: str):
        return None

    monkeypatch.setattr(search, "get_package_info", fake_get_package_info)

    def fake_get(url, timeout):
        class Resp:
            def json(self):
                return {"type": "error", "error": "boom"}

        return Resp()

    monkeypatch.setattr(pkg_mod.requests, "get", fake_get)

    with pytest.raises(AurRPCError):
        search.find_provider("dep")


def test_find_provider_aur_search_request_exception_raises_aur_error(monkeypatch):
    search = PackageSearch()

    def fake_get_package_info(name: str):
        return None

    monkeypatch.setattr(search, "get_package_info", fake_get_package_info)

    class DummyError(pkg_mod.requests.RequestException):
        pass

    def fake_get(url, timeout):
        raise DummyError("boom")

    monkeypatch.setattr(pkg_mod.requests, "get", fake_get)

    with pytest.raises(AurRPCError):
        search.find_provider("dep")


# --- PackageSearch: _choose_provider --------------------------------------


def test_choose_provider_prompts_and_caches(monkeypatch):
    search = PackageSearch()
    providers = ["a", "b", "c"]
    selected_pkg = _make_pkg("b")

    # override prompt to select "2" (provider "b")
    monkeypatch.setattr(
        pkg_mod.output,
        "prompt_number",
        lambda *a, **k: 2,
    )

    def fake_get_package_info(name: str):
        assert name == "b"
        return selected_pkg

    monkeypatch.setattr(search, "get_package_info", fake_get_package_info)

    result = search._choose_provider("dep", providers, "AUR")
    assert result is selected_pkg
    assert search._selected_providers_cache["dep"] is selected_pkg
