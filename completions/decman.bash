# bash completion for decman

_decman() {
    local cur prev opts
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    opts="--source --dry-run --print --debug --skip --only --no-hooks --no-color --params --help"

    case "$prev" in
        --source)
            # file completion
            COMPREPLY=( $(compgen -f -- "$cur") )
            return 0
            ;;
        --skip|--only|--params)
            # free-form list
            return 0
            ;;
    esac

    if [[ "$cur" == --* ]]; then
        COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
        return 0
    fi

    return 0
}
complete -F _decman decman
