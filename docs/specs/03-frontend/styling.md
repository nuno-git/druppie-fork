# Styling

Single-source-of-truth: `frontend/src/index.css` + `frontend/tailwind.config.js`.

## Tailwind

- v3.4.0, utility-first.
- No custom classes except a handful for non-utility concerns.
- Colors consumed through CSS variables (see below) so dark mode could be layered on later.

## CSS custom properties

From `index.css`:

```css
:root {
  --primary: #2563eb;       /* blue-600 */
  --primary-dark: #1d4ed8;  /* blue-700 */
  --secondary: #64748b;     /* slate-500 */
  --success: #22c55e;       /* green-500 */
  --warning: #f59e0b;       /* amber-500 */
  --danger: #ef4444;        /* red-500 */
}
```

Status pills, badges, and agent colors resolve through these tokens so a future theme change is a single-file edit.

## Fonts

System stack only: `-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif`. No web font fetch, no FOUT.

## Scrollbars

Custom webkit scrollbar styling for a thinner bar that matches the palette — applied globally in `index.css`.

## Markdown styling

All rendered markdown is wrapped in a container with class `markdown-content`. `index.css` defines:
- `h1`–`h6` sizes and weights
- `p` margins
- `ul`/`ol` indentation
- `code` vs `pre code` (inline vs block)
- `blockquote` with left border
- `table` with bordered cells
- `img` with rounded corners + max-width
- `a` with `--primary` and underline on hover

## Code syntax highlighting (Prism)

Prism uses the Tomorrow Night token palette mapped to CSS vars in `index.css`:

```css
.token.comment { color: #6c7086 }
.token.keyword { color: #cba6f7 }
.token.string  { color: #a6e3a1 }
...
```

`CodeBlock.jsx` attaches `language-*` class and calls `Prism.highlight(...)` at render time. Supports Python, JS/TS, JSX/TSX, Bash, YAML, JSON, SQL, Markdown, Dockerfile, TOML.

## Toast animations

`.animate-slide-in` keyframe:
```css
@keyframes slide-in {
  from { transform: translateY(100%); opacity: 0; }
  to   { transform: translateY(0);    opacity: 1; }
}
```

Duration 200ms, ease-out. Outgoing slide is reversed.

## Mermaid

Rendered via `mermaid.initialize({ startOnLoad: false, theme: "default" })` once on first `<MermaidBlock>` mount. Pan/zoom is implemented manually (pointer events + CSS transform) — no extra library.

## Responsive

- Mobile breakpoints (sm/md/lg/xl) used sparingly. The Chat page is designed for desktop; on mobile, the SessionSidebar becomes a slide-out drawer.
- NavRail is always 48 px — icons only. Labels appear on hover via tooltip (title attribute).

## Dark mode

Not implemented. The custom properties are in place to make it straightforward — replace `:root` values with a `.dark` class override and toggle on a body class.
