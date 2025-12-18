# fish completion for decman

complete -c decman -l source   -r -d "python file containing configuration" -a "(__fish_complete_path)"
complete -c decman -l dry-run     -d "print what would happen as a result of running decman"
complete -c decman -l print       -d "print what would happen as a result of running decman"
complete -c decman -l debug       -d "show debug output"
complete -c decman -l skip     -r -d "skip the following execution steps"
complete -c decman -l only     -r -d "run only the following execution steps"
complete -c decman -l no-hooks    -d "don't run hook methods for modules"
complete -c decman -l no-color    -d "don't print messages with color"
complete -c decman -l params   -r -d "additional parameters passed to plugins"
