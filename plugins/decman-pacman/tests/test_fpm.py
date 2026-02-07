import typing
from unittest.mock import MagicMock
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from decman.plugins.aur.commands import AurCommands
from decman.plugins.aur.fpm import ForeignPackageManager
from decman.plugins.aur.package import PackageInfo, PackageSearch


class FakeAurPacmanInterface:
    def __init__(self) -> None:
        self.installed_native: set[str] = set()
        self.installed_foreign: dict[str, str] = {}
        self.explicitly_installed: set[str] = set()
        self.not_installable: set[str] = set()
        self.installed_files: list[str] = []  # To track what install_files() actually does
        self.provided_pkgs: set[str] = set()

    def get_native_explicit(self) -> set[str]:
        return self.installed_native.intersection(self.explicitly_installed)

    def get_native_orphans(self) -> set[str]:
        return set()

    def get_foreign_explicit(self) -> set[str]:
        return set(self.installed_foreign.keys()).intersection(self.explicitly_installed)

    def get_dependants(self, package: str) -> set[str]:
        return set()

    def set_as_dependencies(self, packages: set[str]):
        self.explicitly_installed.difference_update(packages)

    def install(self, packages: set[str]):
        self.installed_native.update(packages)
        self.explicitly_installed.update(packages)

    def upgrade(self):
        pass

    def is_provided_by_installed(self, dependency: str) -> bool:
        return dependency in self.provided_pkgs

    def get_all_packages(self) -> set[str]:
        return self.installed_native | self.installed_foreign.keys()

    def filter_installed_packages(self, deps: set[str]) -> set[str]:
        out = set()
        for d in deps:
            if not self.is_provided_by_installed(d) and d not in self.get_all_packages():
                out.add(d)
        return out

    def remove(self, packages: set[str]):
        self.installed_native.difference_update(packages)
        for p in packages:
            self.installed_foreign.pop(p, None)
        self.explicitly_installed.difference_update(packages)

    def get_foreign_orphans(self) -> set[str]:
        return set()

    def is_installable(self, pkg: str) -> bool:
        return pkg not in self.not_installable

    def get_versioned_foreign_packages(self) -> list[tuple[str, str]]:
        return list(self.installed_foreign.items())

    def install_dependencies(self, deps: set[str]):
        self.installed_native.update(deps)

    def install_files(self, files: list[str], as_explicit: set[str]):
        self.installed_files.extend(files)

        for file in files:
            self.installed_foreign[file] = "file"

        for pkg in as_explicit:
            self.explicitly_installed.add(pkg)


class FakeStore:
    def __init__(self) -> None:
        self._store: dict[str, typing.Any] = {}

    def __getitem__(self, key: str) -> typing.Any:
        return self._store[key]

    def __setitem__(self, key: str, value: typing.Any) -> None:
        self._store[key] = value

    def get(self, key: str, default: typing.Any = None) -> typing.Any:
        return self._store.get(key, default)

    def ensure(self, key: str, default: typing.Any = None):
        if key not in self._store:
            self._store[key] = default

    def __enter__(self) -> "FakeStore":
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def save(self) -> None:
        pass

    def __repr__(self) -> str:
        return repr(self._store)


class MockAurServer:
    def __init__(self) -> None:
        self.db: dict[str, dict] = {}  # Maps pkgname -> raw JSON result dict

    def seed(self, packages: list[PackageInfo]):
        for pkg in packages:
            # Reconstruct the raw JSON structure expected by PackageSearch
            entry = {
                "Name": pkg.pkgname,
                "PackageBase": pkg.pkgbase or pkg.pkgname,
                "Version": pkg.version,
                "Description": "Mock Description",
                "URL": "https://example.com",
                "Depends": pkg.dependencies,
                "MakeDepends": pkg.make_dependencies,
                "CheckDepends": pkg.check_dependencies,
                "Provides": pkg.provides,
                # Add other fields if your class relies on them
            }
            self.db[pkg.pkgname] = entry

    def handle_request(self, url, *args, **kwargs):
        parsed = urlparse(url)
        path = parsed.path
        query = parse_qs(parsed.query)

        results = []

        # --- Handle: Multi-info query (.../info?arg[]=pkg1&arg[]=pkg2) ---
        if "/rpc/v5/info" in path and "arg[]" in query:
            requested_names = query["arg[]"]
            for name in requested_names:
                if name in self.db:
                    results.append(self.db[name])

        # --- Handle: Single info query (.../rpc/v5/info/pkgname) ---
        elif "/rpc/v5/info/" in path:
            # Extract package name from end of path
            pkg_name = path.split("/")[-1]
            if pkg_name in self.db:
                results.append(self.db[pkg_name])

        # --- Handle: Search providers (.../rpc/v5/search/dep?by=provides) ---
        elif "/rpc/v5/search/" in path and query.get("by") == ["provides"]:
            search_term = path.split("/")[-1]
            search_term = unquote(search_term)

            # Linear search through DB for 'Provides'
            for entry in self.db.values():
                if search_term in entry.get("Provides", []):
                    results.append(entry)
                # Also match if the package name itself matches the provider request
                elif entry["Name"] == search_term:
                    results.append(entry)

        # Construct the response object
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "version": 5,
            "type": "multiinfo",
            "resultcount": len(results),
            "results": results,
        }

        return mock_response


@pytest.fixture
def mock_aur(mocker):
    server = MockAurServer()
    mocker.patch("requests.get", side_effect=server.handle_request)
    return server


@pytest.fixture
def mock_pacman(mocker):
    pacman = FakeAurPacmanInterface()
    return pacman


@pytest.fixture
def mock_fpm(mocker, mock_aur, mock_pacman):
    mock_builder_cls = mocker.patch("decman.plugins.aur.fpm.PackageBuilder")
    mock_builder_instance = mock_builder_cls.return_value
    mock_builder_instance.__enter__.return_value = mock_builder_instance
    mock_builder_instance.__exit__.return_value = None

    # NOTE: find_latest_cached_package must return a tuple, otherwise
    # the 'assert built_pkg is not None' line in install() will fail.
    def mock_find_cached(store, package):
        # return just the package, so that mock pacman can get the package name from the 'file' name
        return ("1.0.0", package)

    mocker.patch("decman.plugins.aur.fpm.find_latest_cached_package", side_effect=mock_find_cached)
    mocker.patch("decman.plugins.aur.fpm.add_package_to_cache", return_value=None)

    # handle prompts automatically
    mocker.patch("decman.core.output.prompt_confirm", return_value=True)

    store = FakeStore()
    search = PackageSearch()
    commands = AurCommands()
    mgr = ForeignPackageManager(
        store=store,  # type: ignore
        pacman=mock_pacman,
        search=search,
        commands=commands,
        pkg_cache_dir="/tmp/cache",
        build_dir="/tmp/build",
        makepkg_user="nobody",
    )

    return mgr


def test_remove_pacman_deps_provided_by_foreign_packages(
    mock_fpm, mock_aur, mock_pacman: FakeAurPacmanInterface
):
    mock_pacman.not_installable |= {"kwin-hifps", "qt6-base-hifps", "syncthingtray-qt6"}
    pkgs = [
        PackageInfo(
            pkgbase="kwin-hifps",
            pkgname="kwin-hifps",
            version="1",
            git_url="...",
            dependencies=("qt6-base-hifps",),
        ),
        PackageInfo(
            pkgbase="qt6-base-hifps",
            pkgname="qt6-base-hifps",
            version="1",
            git_url="...",
            provides=("qt6-base",),
        ),
        PackageInfo(
            pkgbase="syncthingtray-qt6",
            pkgname="syncthingtray-qt6",
            version="1",
            git_url="...",
            dependencies=("qt6-base",),
        ),
    ]
    mock_aur.seed(pkgs)

    mock_fpm.install(["kwin-hifps", "syncthingtray-qt6"])

    assert len(mock_pacman.installed_files) == 3
    assert mock_pacman.explicitly_installed == {"kwin-hifps", "syncthingtray-qt6"}
    assert "qt6-base" not in mock_pacman.installed_native


def test_remove_pacman_deps_provided_by_already_installed_foreign_packages(
    mock_fpm, mock_aur, mock_pacman: FakeAurPacmanInterface
):
    mock_pacman.not_installable |= {"kwin-hifps", "qt6-base-hifps", "syncthingtray-qt6"}
    pkgs = [
        PackageInfo(
            pkgbase="kwin-hifps",
            pkgname="kwin-hifps",
            version="1",
            git_url="...",
            dependencies=("qt6-base-hifps",),
        ),
        PackageInfo(
            pkgbase="qt6-base-hifps",
            pkgname="qt6-base-hifps",
            version="1",
            git_url="...",
            provides=("qt6-base",),
        ),
        PackageInfo(
            pkgbase="syncthingtray-qt6",
            pkgname="syncthingtray-qt6",
            version="1",
            git_url="...",
            dependencies=("qt6-base",),
        ),
    ]
    mock_pacman.installed_foreign = {
        "kwin-hifps": "1",
        "qt6-base-hifps": "1",
    }
    mock_pacman.explicitly_installed.add("kwin-hifps")
    mock_pacman.provided_pkgs.add("qt6-base")
    mock_aur.seed(pkgs)

    mock_fpm.install(["syncthingtray-qt6"])

    assert len(mock_pacman.installed_files) == 1
    assert mock_pacman.explicitly_installed == {"kwin-hifps", "syncthingtray-qt6"}
    assert "qt6-base" not in mock_pacman.installed_native


def test_install_simple_package(
    mock_fpm, mock_pacman: FakeAurPacmanInterface, mock_aur: MockAurServer
):
    mock_pacman.not_installable.add("foo")
    pkg = PackageInfo(
        pkgbase="foo",
        pkgname="foo",
        version="100.0.0",
        git_url="...",
    )
    mock_aur.seed([pkg])

    mock_fpm.install(["foo"])

    assert len(mock_pacman.installed_files) == 1
    assert "foo" in mock_pacman.installed_files[0]
    assert "foo" in mock_pacman.explicitly_installed
    assert "foo" in mock_pacman.installed_foreign


def test_upgrade_foreign_package(mock_fpm, mock_pacman, mock_aur):
    mock_pacman.not_installable.add("my-app")
    mock_pacman.installed_foreign = {"my-app": "1.0"}
    mock_pacman.explicitly_installed = {"my-app"}

    pkg = PackageInfo(
        pkgbase="my-app",
        pkgname="my-app",
        version="2.0",
        git_url="...",
    )
    mock_aur.seed([pkg])

    mock_fpm.upgrade()

    assert len(mock_pacman.installed_files) == 1
    assert "my-app" in mock_pacman.installed_foreign
    assert "my-app" in mock_pacman.installed_files[0]


def test_upgrade_skips_current_package(mock_fpm, mock_pacman, mock_aur):
    mock_pacman.not_installable.add("stable-app")
    mock_pacman.installed_foreign = {"stable-app": "5.0"}
    mock_pacman.explicitly_installed = {"stable-app"}

    pkg = PackageInfo(
        pkgbase="stable-app",
        pkgname="stable-app",
        version="5.0",
        git_url="...",
    )
    mock_aur.seed([pkg])

    mock_fpm.upgrade()

    assert len(mock_pacman.installed_files) == 0


def test_install_resolves_dependencies(mock_fpm, mock_pacman, mock_aur):
    mock_pacman.not_installable |= {"lib-helper", "main-app"}
    pkg_dep = PackageInfo(pkgbase="lib-helper", pkgname="lib-helper", version="1.5", git_url="...")
    pkg_main = PackageInfo(
        pkgbase="main-app",
        pkgname="main-app",
        version="2.0",
        dependencies=("lib-helper",),
        git_url="...",
    )

    mock_aur.seed([pkg_dep, pkg_main])

    mock_fpm.install(["main-app"])

    assert len(mock_pacman.installed_files) == 2
    assert "main-app" in mock_pacman.explicitly_installed
    assert "main-app" in mock_pacman.installed_files
    assert "lib-helper" in mock_pacman.installed_files
