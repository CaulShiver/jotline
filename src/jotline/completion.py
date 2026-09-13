"""Shell completion scripts generated from the command-line parser.

The scripts ask jotline itself for note IDs, tags, workspaces and actions, so
completion follows any --vault or --workspace already typed on the line.
"""
import argparse
import shlex

SHELLS = ("bash", "zsh", "fish")
ENCODINGS = ("utf-8", "utf-8-sig", "utf-16", "latin-1", "cp1252", "mac-roman")
# Positional arguments whose values jotline can list, keyed by argparse dest.
POSITIONAL_KINDS = {"id": "note", "tags": "tag", "action": "action", "file": "file"}
OPTION_KINDS = {"vault": "dir", "workspace": "workspace", "output": "file"}


def _is_subparsers(action: argparse.Action) -> bool:
    return isinstance(action, argparse._SubParsersAction)


def commands(parser: argparse.ArgumentParser) -> list[tuple[str, argparse.ArgumentParser, str]]:
    for action in parser._actions:
        if _is_subparsers(action):
            helps = {choice.dest: choice.help or "" for choice in action._choices_actions}
            return [(name, sub, helps.get(name, "")) for name, sub in action.choices.items()]
    return []


def value_kind(action: argparse.Action) -> str:
    if action.choices:
        return "words:" + " ".join(action.choices)
    if action.dest == "encoding":
        return "words:" + " ".join(ENCODINGS)
    return OPTION_KINDS.get(action.dest, "none")


def options(parser: argparse.ArgumentParser) -> tuple[list[tuple[str, str]], dict[str, str]]:
    """Long options with their help, and the value kind of each option that takes a value."""
    flags, valued = [], {}
    for action in parser._actions:
        if _is_subparsers(action) or not action.option_strings:
            continue
        for name in (name for name in action.option_strings if name.startswith("--")):
            flags.append((name, action.help or ""))
            if action.nargs != 0:
                valued[name] = value_kind(action)
    return flags, valued


def positionals(parser: argparse.ArgumentParser) -> tuple[list[str], bool]:
    kinds, repeat = [], False
    for action in parser._actions:
        if _is_subparsers(action) or action.option_strings:
            continue
        kinds.append(value_kind(action) if action.choices else POSITIONAL_KINDS.get(action.dest, "none"))
        repeat = action.nargs in ("*", "+")
    return kinds, repeat


BASH = r"""
_jotline_unquote() {
    local value=$1
    value=${value#[\"\']}
    printf '%s' "${value%[\"\']}"
}

_jotline_reply() {
    local IFS=$'\n'
    COMPREPLY=($(compgen -W "$1" -- "$cur"))
}

_jotline_complete_kind() {
    local candidates=""
    case $1 in
        words:*) candidates=${1#words:}; _jotline_reply "${candidates// /$'\n'}"; return ;;
        file|dir)
            local IFS=$'\n'
            type compopt >/dev/null 2>&1 && compopt -o filenames 2>/dev/null
            if [[ $1 == dir ]]; then COMPREPLY=($(compgen -d -- "$cur")); else COMPREPLY=($(compgen -f -- "$cur")); fi
            return ;;
        note) candidates=$(command jotline "${global[@]}" list 2>/dev/null | cut -f1; printf 'last\n') ;;
        tag) candidates=$(command jotline "${global[@]}" tags 2>/dev/null | cut -f1 | sed 's/^#//') ;;
        workspace) candidates=$(command jotline "${global[@]}" workspaces 2>/dev/null | sed 's/ [*]$//') ;;
        action) candidates=$(command jotline "${global[@]}" actions 2>/dev/null) ;;
        *) COMPREPLY=(); return ;;
    esac
    _jotline_reply "$candidates"
}

_jotline() {
    local cur=${COMP_WORDS[COMP_CWORD]} prev=${COMP_WORDS[COMP_CWORD-1]}
    local command="" opts="" valued="" kind="" word i=1 positional=0 dashdash=0 repeat=0
    local -a global=() kinds=()
    COMPREPLY=()
    # Readline splits --option=value at "="; treat the value as its own word.
    if [[ $cur == "=" ]]; then
        cur=""
    elif [[ $prev == "=" ]] && (( COMP_CWORD > 1 )); then
        prev=${COMP_WORDS[COMP_CWORD-2]}
    fi
    while (( i < COMP_CWORD )); do
        word=${COMP_WORDS[i]}
        if [[ -z $command ]]; then
            case $word in
                @GLOBAL_PATTERN@)
                    if [[ ${COMP_WORDS[i+1]} == "=" ]]; then
                        (( i + 2 < COMP_CWORD )) && global+=("$word=$(_jotline_unquote "${COMP_WORDS[i+2]}")")
                        (( i += 3 ))
                    else
                        (( i + 1 < COMP_CWORD )) && global+=("$word" "$(_jotline_unquote "${COMP_WORDS[i+1]}")")
                        (( i += 2 ))
                    fi
                    continue ;;
                -*) ;;
                *)
                    command=$word
                    case $command in
@COMMAND_ARMS@
                    esac ;;
            esac
        elif (( dashdash )); then
            (( positional += 1 ))
        elif [[ $word == -- ]]; then
            dashdash=1
        elif [[ $word == -* ]]; then
            if [[ $word != *=* && " $valued " == *" $word "* ]]; then
                if [[ ${COMP_WORDS[i+1]} == "=" ]]; then (( i += 2 )); else (( i += 1 )); fi
            fi
        elif [[ $word != "=" ]]; then
            (( positional += 1 ))
        fi
        (( i += 1 ))
    done
    if [[ -z $command && " @GLOBAL_VALUED@ " == *" $prev "* ]] || [[ -n $command && " $valued " == *" $prev "* ]]; then
        case $prev in
@VALUE_ARMS@
        esac
        _jotline_complete_kind "$kind"
        return
    fi
    if [[ -z $command ]]; then
        if [[ $cur == -* ]]; then _jotline_reply @GLOBAL_FLAGS@; else _jotline_reply @COMMANDS@; fi
        return
    fi
    if (( ! dashdash )) && [[ $cur == -* ]]; then
        _jotline_reply "${opts// /$'\n'}"
        return
    fi
    if (( positional < ${#kinds[@]} )); then
        kind=${kinds[positional]}
    elif (( repeat && ${#kinds[@]} > 0 )); then
        kind=${kinds[${#kinds[@]}-1]}
    fi
    _jotline_complete_kind "$kind"
}

complete -F _jotline jotline
"""


def bash_body(parser: argparse.ArgumentParser) -> str:
    global_flags, global_valued = options(parser)
    valued = dict(global_valued)
    arms = []
    for name, sub, _ in commands(parser):
        flags, sub_valued = options(sub)
        kinds, repeat = positionals(sub)
        valued.update(sub_valued)
        arms.append(f"                        {name}) opts={shlex.quote(' '.join(flag for flag, _ in flags))}; "
                    f"valued={shlex.quote(' '.join(sub_valued))}; "
                    f"kinds=({' '.join(shlex.quote(kind) for kind in kinds)}); repeat={int(repeat)} ;;")
    replacements = {
        "@GLOBAL_PATTERN@": "|".join(global_valued),
        "@GLOBAL_VALUED@": " ".join(global_valued),
        "@COMMAND_ARMS@": "\n".join(arms),
        "@VALUE_ARMS@": "\n".join(f"            {option}) kind={shlex.quote(kind)} ;;" for option, kind in valued.items()),
        "@GLOBAL_FLAGS@": shlex.quote("\n".join(flag for flag, _ in global_flags)),
        "@COMMANDS@": shlex.quote("\n".join(name for name, _, _ in commands(parser))),
    }
    body = BASH
    for marker, value in replacements.items():
        body = body.replace(marker, value)
    return body


def bash_script(parser: argparse.ArgumentParser) -> str:
    return '# Bash completion for jotline. Load it with: eval "$(jotline completion bash)"' + bash_body(parser)


def zsh_script(parser: argparse.ArgumentParser) -> str:
    # Zsh runs bash completion functions through bashcompinit, in sh emulation.
    return ('# Zsh completion for jotline. Load it after compinit with: eval "$(jotline completion zsh)"\n'
            "autoload -U +X bashcompinit && bashcompinit" + bash_body(parser))


FISH = r"""# Fish completion for jotline. Load it with: jotline completion fish | source
function __jotline_tokens
    commandline -xpc 2>/dev/null; or commandline -opc
end

function __jotline_valued
    switch $argv[1]
@FISH_VALUED@
    end
end

function __jotline_value_kind
    switch $argv[1]
@FISH_VALUE_KINDS@
    end
end

function __jotline_positional_kind
    set -l index (math $argv[2] + 1)
    set -l kinds
    set -l repeat 0
    switch $argv[1]
@FISH_POSITIONALS@
    end
    if test $index -le (count $kinds)
        echo $kinds[$index]
    else if test $repeat -eq 1; and set -q kinds[1]
        echo $kinds[-1]
    else
        echo none
    end
end

# Prints the subcommand (or -) and the kind of value the current token needs.
function __jotline_state
    set -l tokens (__jotline_tokens)
    set -e tokens[1]
    set -l command
    set -l valued
    set -l expect
    set -l positional 0
    set -l dashdash 0
    for token in $tokens
        if test -n "$expect"
            set expect
            continue
        end
        if test -z "$command"
            if contains -- $token @FISH_GLOBAL_VALUED@
                set expect $token
            else if not string match -q -- '-*' $token
                set command $token
                set valued (__jotline_valued $command)
            end
        else if test $dashdash -eq 1
            set positional (math $positional + 1)
        else if test "$token" = --
            set dashdash 1
        else if string match -q -- '-*' $token
            if contains -- $token $valued
                set expect $token
            end
        else
            set positional (math $positional + 1)
        end
    end
    if test -n "$command"
        echo $command
    else
        echo -
    end
    if test -n "$expect"
        __jotline_value_kind $expect
    else if test -z "$command"
        echo command
    else
        __jotline_positional_kind $command $positional
    end
end

function __jotline_is
    set -l state (__jotline_state)
    string match -q -- $argv[1] $state[2]
end

function __jotline_in
    set -l state (__jotline_state)
    test "$state[1]" = $argv[1]
end

# Runs jotline with the --vault and --workspace options already on the line.
function __jotline_run
    set -l tokens (__jotline_tokens)
    set -e tokens[1]
    set -l global
    set -l expect
    for token in $tokens
        if test -n "$expect"
            set -a global $expect $token
            set expect
        else if contains -- $token @FISH_GLOBAL_VALUED@
            set expect $token
        else if string match -q -- '--*=*' $token
            set -a global $token
        else if not string match -q -- '-*' $token
            break
        end
    end
    command jotline $global $argv 2>/dev/null
end

function __jotline_notes
    for line in (__jotline_run list)
        set -l fields (string split \t -- $line)
        printf '%s\t%s\n' $fields[1] $fields[3]
    end
    printf 'last\tMost recently updated note\n'
end

function __jotline_tags
    for line in (__jotline_run tags)
        set -l fields (string split \t -- $line)
        printf '%s\t%s notes\n' (string replace '#' '' -- $fields[1]) $fields[2]
    end
end

function __jotline_workspaces
    __jotline_run workspaces | string replace -r ' \*$' ''
end

function __jotline_words
    set -l state (__jotline_state)
    string split ' ' -- (string replace 'words:' '' -- $state[2])
end

# Fish completes an option's value only from that option's own line, so value
# candidates are attached to the options below; these cover positionals.
complete -c jotline -f
complete -c jotline -n '__jotline_is note' -a '(__jotline_notes)'
complete -c jotline -n '__jotline_is tag' -a '(__jotline_tags)'
complete -c jotline -n '__jotline_is action' -a '(__jotline_run actions)'
complete -c jotline -n '__jotline_is "words:*"' -a '(__jotline_words)'
complete -c jotline -n '__jotline_is file' -F
"""


def fish_quote(text: str) -> str:
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def fish_value_args(kind: str | None) -> str:
    if kind is None:
        return ""
    if kind.startswith("words:"):
        return " -x -a " + fish_quote(kind.removeprefix("words:"))
    if kind == "file":
        return " -r -F"
    functions = {"dir": "__fish_complete_directories", "workspace": "__jotline_workspaces"}
    return f" -x -a '({functions[kind]})'" if kind in functions else " -r"


def fish_script(parser: argparse.ArgumentParser) -> str:
    global_flags, global_valued = options(parser)
    valued = dict(global_valued)
    valued_arms, positional_arms, lines = [], [], []
    for name, _, help_text in commands(parser):
        lines.append(f"complete -c jotline -n '__jotline_is command' -a {name} -d {fish_quote(help_text)}")
    for flag, help_text in global_flags:
        lines.append(f"complete -c jotline -n '__jotline_in -' -l {flag[2:]}"
                     f"{fish_value_args(global_valued.get(flag))} -d {fish_quote(help_text)}")
    for name, sub, _ in commands(parser):
        flags, sub_valued = options(sub)
        kinds, repeat = positionals(sub)
        valued.update(sub_valued)
        if sub_valued:
            valued_arms.append(f"        case {name}\n            printf '%s\\n' {' '.join(sub_valued)}")
        if kinds:
            positional_arms.append(f"        case {name}\n            set kinds {' '.join(fish_quote(kind) for kind in kinds)}"
                                   + ("\n            set repeat 1" if repeat else ""))
        for flag, help_text in flags:
            lines.append(f"complete -c jotline -n '__jotline_in {name}' -l {flag[2:]}"
                         f"{fish_value_args(sub_valued.get(flag))} -d {fish_quote(help_text)}")
    replacements = {
        "@FISH_VALUED@": "\n".join(valued_arms),
        "@FISH_VALUE_KINDS@": "\n".join(f"        case -- {option}\n            echo {fish_quote(kind)}"
                                        for option, kind in valued.items()),
        "@FISH_POSITIONALS@": "\n".join(positional_arms),
        "@FISH_GLOBAL_VALUED@": " ".join(global_valued),
    }
    body = FISH
    for marker, value in replacements.items():
        body = body.replace(marker, value)
    return body + "\n".join(lines) + "\n"


def script(shell: str, parser: argparse.ArgumentParser) -> str:
    return {"bash": bash_script, "zsh": zsh_script, "fish": fish_script}[shell](parser)
