-- Jotline quick capture in a small floating terminal.
-- Reload with: hyprctl reload
-- List used keys: omarchy menu keybindings --print
o.bind("SUPER + SHIFT + J", "Jotline capture",
  "uwsm-app -- xdg-terminal-exec --app-id=org.jotline.capture --title=Jotline -e __JOTLINE__ capture")
o.window("^org.jotline.capture$", { float = true, center = true, size = { 760, 420 } })
