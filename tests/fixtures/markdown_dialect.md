# Shared Markdown corpus

Text with **strong**, *emphasis*, ~~strikethrough~~, `inline code`, and café 日本語.

The first reference[^β] repeats[^β]; another[^引用] and an undefined one[^missing].

| Feature | Status |
| --- | --- |
| Table | rendered |
| Footnote | [^引用] |

- [ ] Unfinished task
- [x] Finished task

An [ordinary reference][site] and an <https://example.invalid/autolink>.

[site]: https://example.invalid/reference "Reference title"

<script>alert("not executable")</script>

<img src="file:///private/never-read.png" onerror="alert(1)">

![Remote image](https://example.invalid/never-fetch.png)
![Local image](file:///private/never-read.png)
[Unsafe URI](javascript:alert(1))
[Unsafe reference][unsafe]

[unsafe]: javascript:alert(1)

```markdown
- [ ] Fenced task stays literal
[^β]: Fenced definition stays literal
![Not an image](https://example.invalid/fenced.png)
```

An inline `[^β]` stays literal too.

[^β]: Superseded duplicate body.

[^β]: Chosen duplicate body with **formatting** and café.

    A second paragraph with a [safe link](https://example.invalid/footnote).

[^引用]: Unicode definition with *emphasis*.

[^unused]: Unreferenced definitions are not displayed.
