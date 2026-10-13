"""Shell-completion script generation for the `cyberboard` CLI.

`cyberboard completion {bash,zsh,fish}` prints a completion script to stdout.
The top-level command list is passed in from `cli.COMMANDS` (the single source
of truth), so completion stays in sync automatically when a command is added.
Second-level actions for the few multi-action commands are passed via
`subcommands` (mirroring each tool's subparsers) to make completion feel
complete; beyond that, completion falls back to file names.

Kept dependency-free and out of the dispatch table on purpose: this is a
CLI-meta feature, not keyboard logic, so it lives in the package rather than
in a `tools/cb_*` module.
"""
from __future__ import annotations

SHELLS = ("bash", "zsh", "fish")


def _clean(desc: str) -> str:
    """Sanitize a help string for embedding in a completion description.

    `:` separates name from description in zsh `_describe`, and `'` would
    close the single-quoted literals we emit for zsh/fish — strip both so a
    help string can never break the generated script.
    """
    return desc.replace(":", " ").replace("'", "")


def script(shell: str, commands: list[tuple[str, str]],
           subcommands: dict[str, list[str]]) -> str:
    """Return a completion script for `shell` (one of SHELLS).

    `commands` is an ordered list of (name, help); `subcommands` maps a
    command name to its second-level action names.
    """
    if shell == "bash":
        return _bash(commands, subcommands)
    if shell == "zsh":
        return _zsh(commands, subcommands)
    if shell == "fish":
        return _fish(commands, subcommands)
    raise ValueError(f"unsupported shell {shell!r} (have: {', '.join(SHELLS)})")


def _bash(commands: list[tuple[str, str]], subcommands: dict[str, list[str]]) -> str:
    names = " ".join(name for name, _ in commands)
    cases = "\n".join(
        f'        {cmd}) [ "$cword" -eq 2 ] && '
        f'COMPREPLY=( $(compgen -W "{" ".join(actions)}" -- "$cur") ) && return ;;'
        for cmd, actions in subcommands.items()
    )
    return f"""# cyberboard bash completion. Install: cyberboard completion bash > \\
#   /usr/local/etc/bash_completion.d/cyberboard   (or source it from ~/.bashrc)
_cyberboard() {{
    local cur prev cword
    if declare -F _init_completion >/dev/null 2>&1; then
        _init_completion || return
    else
        cur="${{COMP_WORDS[COMP_CWORD]}}"
        prev="${{COMP_WORDS[COMP_CWORD-1]}}"
        cword=$COMP_CWORD
    fi
    local commands="{names}"
    if [ "$cword" -eq 1 ]; then
        COMPREPLY=( $(compgen -W "$commands -h --help -V --version" -- "$cur") )
        return
    fi
    case "${{COMP_WORDS[1]}}" in
{cases}
    esac
    COMPREPLY=( $(compgen -f -- "$cur") )
}}
complete -F _cyberboard cyberboard
"""


def _zsh(commands: list[tuple[str, str]], subcommands: dict[str, list[str]]) -> str:
    entries = "\n".join(
        f"    '{name}:{_clean(help_text)}'" for name, help_text in commands
    )
    cases = "\n".join(
        f"        {cmd}) (( CURRENT == 3 )) && "
        f"_values 'action' {' '.join(actions)} && return ;;"
        for cmd, actions in subcommands.items()
    )
    return f"""#compdef cyberboard
# cyberboard zsh completion. Install: cyberboard completion zsh > \\
#   "${{fpath[1]}}/_cyberboard"   (then restart the shell)
_cyberboard() {{
  local -a commands
  commands=(
{entries}
  )
  if (( CURRENT == 2 )); then
    _describe -t commands 'cyberboard command' commands
    return
  fi
  case "$words[2]" in
{cases}
  esac
  _files
}}
_cyberboard "$@"
"""


def _fish(commands: list[tuple[str, str]], subcommands: dict[str, list[str]]) -> str:
    top = "\n".join(
        f"complete -c cyberboard -n __fish_use_subcommand -a {name} "
        f"-d '{_clean(help_text)}'"
        for name, help_text in commands
    )
    subs = "\n".join(
        f"complete -c cyberboard -n '__fish_seen_subcommand_from {cmd}' "
        f"-a '{' '.join(actions)}'"
        for cmd, actions in subcommands.items()
    )
    return f"""# cyberboard fish completion. Install: cyberboard completion fish > \\
#   ~/.config/fish/completions/cyberboard.fish
{top}
{subs}
"""
