# Theme coverage

Jotline exposes all 21 built-in Textual themes plus its own Jotline theme. The
selection deliberately favors maintained, built-in palettes over third-party
theme packages: every choice works with the installed Textual version without
an additional download, compatibility layer, or unpinned dependency.

## Evidence and decision

The existing collection already covered the most broadly adopted named terminal
and editor palettes: Dracula, Nord, Gruvbox, Tokyo Night, Monokai, Solarized,
Catppuccin, Flexoki, and Rosé Pine. Popularity is necessarily an imperfect
measure—different editors publish different install metrics—but cross-platform
adoption and the availability of an official palette are useful, durable
proxies. For example, Dracula's official project reports support for more than
400 applications and 23,000+ GitHub stars; Solarized is a long-lived,
cross-application terminal/editor palette; and One Dark was bundled with Atom.

The remaining Textual themes are now enabled:

| Theme | Rationale |
| --- | --- |
| `atom-one-dark` / `atom-one-light` | One Dark is a familiar editor palette, historically bundled with Atom. |
| `textual-dark` | Textual's own dark counterpart to the already available `textual-light`. |
| `ansi-dark` / `ansi-light` | Practical high-compatibility choices for users who prefer conventional terminal colors. |

This completes the framework's built-in catalog, so the Settings theme picker
has 22 choices including `jotline`. Textual documents that built-in themes are
registered by default, that the active theme can change at runtime, and that
theme variables update the application UI. The implementation therefore only
allowlists these already-shipped choices in Jotline; it does not add a runtime
dependency.

## Sources

1. Textualize. [Themes](https://textual.textualize.io/guide/design/). Accessed September 13, 2026. Documents Textual's built-in themes, runtime selection, and theme-variable behavior.
2. Textualize. [Textual repository](https://github.com/Textualize/textual). Accessed September 13, 2026. Describes predefined themes supplied with the framework.
3. Dracula Theme. [dracula-theme](https://github.com/dracula/dracula-theme). Accessed September 13, 2026. Project adoption and cross-application support.
4. Ethan Schoonover. [Solarized](https://github.com/altercation/solarized). Accessed September 13, 2026. Original palette and terminal/editor scope.
5. Atom. [One Dark UI](https://github.com/atom/one-dark-ui). Accessed September 13, 2026. Documents One Dark as a bundled Atom theme.
