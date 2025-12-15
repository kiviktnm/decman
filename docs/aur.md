# AUR

> [!NOTE]
> Building of foreign packages is not the primary function of decman. There are some issues that I may or may not fix.
> If you can't build a package using decman, consider adding it to `ignored_packages` and building it yourself.

Decman can install AUR packages as well as user defined packages. Foreign packages are AUR and user packages combined.

Here is an example of a user package. Managing user packages is somewhat cumbersome as you have to declare their versions, dependencies and make dependencies manually. However, you probably won't install many user packages anyway.

```py
# Note, decman now has a aur package, I recommend using that instead.
# Also, this example may be out of date
decman.user_packages.append(
    decman.UserPackage(
        pkgname="decman-git",
        provides=["decman"],
        version="0.4.1",
        dependencies=["python", "python-requests", "devtools", "pacman", "systemd", "git"],
        make_dependencies=[
            "python-setuptools", "python-build", "python-installer", "python-wheel"
        ],
        git_url="https://github.com/kiviktnm/decman-pkgbuild.git",
    ))
```

Building of foreign packages happens in a chroot. This creates some overhead, but ensures clean builds. By default the chroot is created to `/tmp/decman/build`. I recommend to use a tmpfs for the `/tmp/` directory to speed up builds. Also make sure that the tmpfs-partition is large enough. I recommend at least 6 GB.

Build packages are stored in a cache `/var/cache/decman`. By default decman keeps 3 most recent versions of all packages.
