# Pacman

Decman can be used to install pacman packages. Decman will install all packages defined in the source and **remove** all explicitly installed packages not defined in the source. You don't need to list dependencies as those will be handeled by pacman. You can set packages to be ignored by decman, so that it won't install them nor remove them.

Please keep in mind that decman doesn't play well with package groups, since all packages part of that group will be installed explicitly. After the initial run decman will now try to remove those packages since it only knows that the group itself should be explicitly installed. Instead of package groups, use meta packages.

```py
# Include only pacman packages found in the pacman repositories in here.
decman.pacman.ignored_packages |= {"opendoas"}

# Decman will highlight text from pacman commands according to these keywords,
# if the feauture is enabled. These are the defaults.
decman.pacman.print_highlights = True
decman.pacman.keywords = {"pacsave", "pacnew" }
```
