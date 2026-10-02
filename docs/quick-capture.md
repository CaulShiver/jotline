# Quick capture from anywhere

Run `jotline capture` in a terminal without any text and it opens a small
editor instead of the full app:

- **Ctrl+S** saves the text as a new note in your default collection and
  confirms it: `Saved to inbox: <title> (<short id>)`.
- **Esc** cancels. If you have typed something, press Esc twice so a stray key
  cannot throw it away. **Ctrl+Q** saves rather than discarding.
- `jotline capture --daily` appends to today's log instead (`Added to daily
  log <date>`), and `jotline capture --daily --date yesterday` appends to
  another day.
- `jotline --workspace work capture` captures into an existing workspace. To
  start a new one from the shell, add `--new-workspace`.

Closing the window any other way discards the text.

## Desktop launcher

On Linux, install a `jotline capture` desktop entry and bind one command:

```sh
jotline desktop install
jotline desktop launch
```

`jotline desktop launch` opens capture in a terminal; `jotline desktop launch
--daily` appends to today's log instead. Add `--vault` or `--workspace` and the
launcher passes them on. A launcher bound to a workspace also passes
`--new-workspace`, so its first capture can create that workspace instead of
failing in a window that closes before you can read why. GNOME and KDE can bind that
command (or the **Jotline Capture** app after install) as a custom shortcut.
Hyprland and Omarchy need a window rule as well; print a filled-in snippet:

```sh
jotline desktop recipe omarchy
jotline desktop recipe hyprland
jotline desktop recipe gnome
jotline desktop recipe kde
jotline desktop recipe pipe
```

`jotline desktop` shows whether the launcher is installed. `jotline desktop
uninstall` removes the desktop entry Jotline wrote. Recipes substitute the
`jotline` path for this install. Write one to a file with
`jotline desktop recipe hyprland --output ~/.config/hypr/jotline.conf`.

## Choosing the terminal

`jotline desktop launch` looks for a terminal in this order, putting the ones
that suit your desktop (from `XDG_CURRENT_DESKTOP`) first: kitty, alacritty,
foot, ghostty, wezterm, ptyxis, kgx, gnome-terminal, konsole, xfce4-terminal and
xdg-terminal-exec. Hyprland and Omarchy prefer kitty, foot, alacritty, ghostty
and wezterm; GNOME prefers ptyxis, kgx and gnome-terminal; KDE prefers konsole.

Set `JOTLINE_TERMINAL` to pick one yourself, by name or full path, for example
`JOTLINE_TERMINAL=foot jotline desktop launch`. It must be one of the terminals
above; anything else is refused with the list. When no terminal is found and the
command already runs in one, capture opens right there; otherwise the error
suggests setting `JOTLINE_TERMINAL`, printing a recipe, or piping text.

There is no dictation, share sheet, or cloud. Pipe-in stays the integration for
launchers that cannot open a terminal.

## Omarchy

Omarchy's Hyprland configuration is written in Lua. Paste the output of
`jotline desktop recipe omarchy` into `~/.config/hypr/bindings.lua`, then run
`hyprctl reload` (or log out and back in). The shipped snippet is:

```lua
-- Jotline quick capture in a small floating terminal.
-- Reload with: hyprctl reload
-- List used keys: omarchy menu keybindings --print
o.bind("SUPER + SHIFT + J", "Jotline capture",
  "uwsm-app -- xdg-terminal-exec --app-id=org.jotline.capture --title=Jotline -e jotline capture")
o.window("^org.jotline.capture$", { float = true, center = true, size = { 760, 420 } })
```

Pick a key that is still free; `omarchy menu keybindings --print` lists the
current bindings. If the hotkey cannot find `jotline`, the recipe command
prints the full path.

## Other Hyprland setups

`jotline desktop recipe hyprland` prints window rules plus a bind for
`jotline desktop launch`. In `hyprland.conf`:

```ini
windowrulev2 = float, class:^(org.jotline.capture)$
windowrulev2 = size 760 420, class:^(org.jotline.capture)$
windowrulev2 = center, class:^(org.jotline.capture)$
bind = SUPER SHIFT, J, exec, jotline desktop launch
```

Or spawn a known terminal yourself:
`kitty --class org.jotline.capture -e jotline capture`,
`alacritty --class org.jotline.capture -e jotline capture`,
`foot --app-id=org.jotline.capture jotline capture`, or
`ghostty --class=org.jotline.capture -e jotline capture`.

## GNOME and KDE

`jotline desktop install`, then add a custom keyboard shortcut whose command is
`jotline desktop launch` (GNOME: Settings → Keyboard → Custom Shortcuts; KDE:
System Settings → Shortcuts → Add New → Command). After install you can also
use `gtk-launch org.jotline.capture`.

## macOS

Windows is out of scope. On macOS, bind a terminal hotkey to `jotline capture`,
or pipe the clipboard. `jotline desktop recipe pipe` prints the clipboard
commands.

## Piping instead of typing

Any launcher that can run a command without a terminal can still capture a
line of text: `wl-paste | jotline capture` saves the clipboard as a note.
On macOS use `pbpaste | jotline capture`.
