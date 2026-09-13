# Quick capture from anywhere

Run `jotline capture` in a terminal without any text and it opens a small
editor instead of the full app:

- **Ctrl+S** saves the text as a new note in your default collection and prints its ID.
- **Esc** cancels. If you have typed something, press Esc twice so a stray key
  cannot throw it away. **Ctrl+Q** saves rather than discarding.
- `jotline capture --daily` appends to today's log instead, and
  `jotline --workspace work capture` captures into another workspace.

Closing the window any other way discards the text.

Bind that command to a global key and a thought is two keystrokes from saved.
The recipes below open it in a small floating terminal window.

## Omarchy

Omarchy's Hyprland configuration is written in Lua. Add these lines to
`~/.config/hypr/bindings.lua`, then run `hyprctl reload` (or log out and back in):

```lua
-- Jotline quick capture in a small floating terminal.
o.bind("SUPER + SHIFT + J", "Jotline capture",
  "uwsm-app -- xdg-terminal-exec --app-id=org.jotline.capture --title=Jotline -e jotline capture")
o.window("^org.jotline.capture$", { float = true, center = true, size = { 760, 420 } })
```

Pick a key that is still free; `omarchy menu keybindings --print` lists the
current bindings. If the hotkey cannot find `jotline`, use its full path, such as
`~/.local/bin/jotline` (which `command -v jotline` prints).

## Other Hyprland setups

In `hyprland.conf`, an exec rule floats the window without a separate window rule:

```ini
bind = SUPER SHIFT, J, exec, [float; size 760 420; center] kitty --class org.jotline.capture -e jotline capture
```

Swap in your terminal: `alacritty --class org.jotline.capture -e jotline capture`,
`foot --app-id=org.jotline.capture jotline capture`, or
`ghostty --class=org.jotline.capture -e jotline capture`.

## GNOME and KDE

Add a custom keyboard shortcut (GNOME: Settings → Keyboard → Custom Shortcuts;
KDE: System Settings → Shortcuts → Add New → Command) that runs your terminal
with the capture command, for example
`gnome-terminal --title=Jotline -- jotline capture` or
`konsole -e jotline capture`.

## Piping instead of typing

Any launcher that can run a command without a terminal can still capture a
line of text: `wl-paste | jotline capture` saves the clipboard as a note.
