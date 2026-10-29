# Markdown dialect and offline rendering

Jotline keeps your note as plain Markdown. Full preview, side-by-side preview,
and HTML export use the same parser and footnote numbering. Word and PDF
exports start from that HTML; the installed converter controls their final
layout. Exporting Markdown leaves the source unchanged.

## Supported syntax

The base dialect is **CommonMark**, with these extensions:

- Pipe tables and `~~strikethrough~~`.
- Tasks written as `- [ ]` or `- [x]`, displayed as text checkboxes.
- Jotline `[[note links]]`, clickable in preview and printed as labels in
  exports. See [links and connections](writing.md#links-and-connections).
- Named footnotes, using `[^label]` and `[^label]: Definition`.
- Stable heading fragments and a keyboard **Jump to heading** table of
  contents. Duplicate headings receive distinct fragment IDs.

Normal Markdown links, reference-style links (`[label][reference]`), explicit
autolinks (`<https://example.com>`), fenced and indented code, and inline code
are supported. Bare URLs are not automatically turned into links. Task and
note-link examples inside fenced code remain literal.

## Footnotes

```markdown
A claim[^source], followed by the same reference[^source].

[^source]: The source, with **formatting** and an ordinary Markdown link.

    Indent additional paragraphs by four spaces.
```

Footnotes appear at the end, numbered by their first reference, not by
definition order. Repeated references share a number and get separate return
links. In preview, click a reference to scroll to its definition, or click
`↩` to return to the paragraph containing the reference. A reference in a
table returns to that table. HTML exports provide the same local links.
In full preview, **Ctrl+T** opens **Contents**: choose **Footnote N** to reach
its definition, or **Return to footnote N reference** to reach its first
reference using the keyboard. Inline links themselves are not individually
keyboard-focusable in the terminal widget; pointer backlinks can return to
each repeated reference separately.

Labels may contain Unicode, but are case-sensitive and must contain 1–200
characters with no whitespace or square brackets. Use the same Unicode
spelling in the reference and definition. Generated IDs are numeric and do
not contain label text. The label limit keeps malformed imported Markdown
from causing expensive repeated scans.

Undefined references stay visible as `[^missing]`. Unreferenced definitions
are omitted from rendered output, and the **last definition wins** when a
label is defined more than once. Fenced and inline code do not create
footnotes. Inline `^[footnote text]` syntax is not supported. Footnote-like
syntax outside the label rules is processed as ordinary Markdown instead.

## Headings and local navigation

**Ctrl+P → Table of contents** (also available as **Jump to heading**) moves
the editor to a heading without changing the note. In full preview,
**Ctrl+T** or **Contents** opens the local heading/footnote picker. The heading
index understands both `# Heading` and underlined setext headings, including
headings nested in quotes or lists; code examples are not headings.

Use `[Section](#section)` for a local Markdown link, `[[#Heading]]` for a local
Jotline link, or `[[note#Heading]]` / `[[note-id#section-1]]` for another note's
heading. Exact note titles containing `#` take priority over interpreting the
character as a heading separator. Exported wiki links remain plain labels,
not links to other exported files.

Fragment IDs normalize Unicode to NFC and case-fold it, remove punctuation,
and replace whitespace with hyphens. Duplicate stems receive `-1`, `-2`, and
so on without colliding with existing IDs. An empty stem becomes `section`;
the `jl-footnote-` prefix is reserved for footnotes, so such heading stems are
prefixed with `section-`.

Heading anchors remain stable until the heading text or duplicate order
changes. For a permanent block destination, use Jotline's existing `#^block`
references instead. A bare `[[note-id]]` inside a heading intentionally stays
an ID rather than expanding to the current note title, keeping its fragment
independent of a title lookup or rename; use `[[note-id|Readable label]]` for
an explicit heading label.

## Safety and rendering differences

- Rendering is offline. Nothing in the note can fetch a remote resource or
  read a local image file.
- Raw HTML is displayed as text, never executed. HTML exports also carry a
  restrictive Content Security Policy.
- Images are represented without loading them: an image label/link in HTML,
  and a terminal image marker with its label in preview.
- Unsafe link schemes rejected by the Markdown parser (such as `javascript:`)
  do not become links. Preview never opens external URLs; only supported
  local heading/footnote and Jotline note links are followed.
- HTML viewers may open ordinary links when you explicitly click them.
  Jotline's offline rendering promise does not disable your browser's normal
  navigation.
- Fonts, checkbox glyphs, line wrapping, syntax colors, and table layout vary
  by terminal, browser, and document converter. The source text and parsing
  rules stay the same.

The regression corpus in `tests/fixtures/markdown_dialect.md` is synthetic and
covers tables, tasks, footnotes, reference links, raw HTML, unsafe URIs,
images, code fences, duplicate labels, undefined references, and Unicode.
