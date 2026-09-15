# Omarchy theme follow

On Omarchy, select **Ctrl+, → Appearance → Omarchy (follow desktop)** to follow
your desktop palette, including its cursor and selection background. Changes
refresh within about a second, including in quick capture, without restarting or
losing your selection. Markdown keeps its syntax foreground colors while selected.

Jotline reads `omarchy/current/theme/colors.toml` under the XDG state directory
(`~/.local/state` by default), with support for older config-directory layouts.
Missing or invalid palettes keep the last good colors (Jotline colors on first
launch). Choose any other theme to stop following Omarchy.
