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

## Jotline-defined palettes

Eight palettes are defined in `src/jotline/themes.py` as plain data. Hex values
come from each project's published palette (all MIT licensed). Where an
official accent fell below 4.5:1 against its background, it was darkened
within the same family. `tests/test_themes.py` checks foreground, primary and
accent contrast for every one.

- `jotline-light` is the light sibling of the default: warm paper, dark
  green-gray text, a darker green accent.
- `everforest-dark` and `everforest-light` (medium contrast) give a soft,
  low-glare pair for long writing sessions. [sainnhe/everforest](https://github.com/sainnhe/everforest).
- `kanagawa` is the "wave" variant, a muted dark palette. [rebelot/kanagawa.nvim](https://github.com/rebelot/kanagawa.nvim).
- `gruvbox-light` completes the pair with the dark `gruvbox` Textual ships (medium contrast). [morhetz/gruvbox](https://github.com/morhetz/gruvbox).
- `tokyo-night-day` is the light counterpart of `tokyo-night`. [folke/tokyonight.nvim](https://github.com/folke/tokyonight.nvim).
- `ayu-mirage` is the mid-dark Ayu variant. [ayu-theme/ayu-colors](https://github.com/ayu-theme/ayu-colors).
- `high-contrast` is pure black with white text and yellow and cyan accents for low-vision users.

On light themes the current-line band is a 7% darkening of the page. The old
rule picked the lighter or darker shade that differed more, which produced a
heavy mid-gray on light backgrounds.

## Sources

1. Textualize. [Themes](https://textual.textualize.io/guide/design/). Accessed September 13, 2026. Documents Textual's built-in themes, runtime selection, and theme-variable behavior.
2. Textualize. [Textual repository](https://github.com/Textualize/textual). Accessed September 13, 2026. Describes predefined themes supplied with the framework.
3. Dracula Theme. [dracula-theme](https://github.com/dracula/dracula-theme). Accessed September 13, 2026. Project adoption and cross-application support.
4. Ethan Schoonover. [Solarized](https://github.com/altercation/solarized). Accessed September 13, 2026. Original palette and terminal/editor scope.
5. Atom. [One Dark UI](https://github.com/atom/one-dark-ui). Accessed September 13, 2026. Documents One Dark as a bundled Atom theme.
