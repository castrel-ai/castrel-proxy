---
name: pptx-generator
description: "Design, generate, validate, edit, and review presentation slide decks as editable Castrel Slide IR JSON. Triggers: presentation, slide, deck, slides, PPT, PowerPoint, slide validation."
license: MIT
metadata:
  version: "1.2.0"
  category: productivity
  upstream:
    repository: https://github.com/MiniMax-AI/skills
    directory: skills/pptx-generator
    ref: main
---

# Presentation Deck Design

This skill carries the official MiniMax presentation design methodology into
Castrel. It is a design and authoring guide for editable Slide IR JSON.

## Castrel Output Contract

- The only deliverable is a `slides_ir` JSON document.
- Use the exact Castrel Slide IR schema supplied by the proxy instructions.
- Use a logical canvas of `1000 × 562.5` pixels.
- Use absolute `left`, `top`, `width`, and `height` coordinates.
- Keep slide and element IDs deterministic and stable across revisions.
- Preserve existing IDs during edits; update existing elements instead of
  recreating them unnecessarily.
- Every element must have a unique non-empty `id`. Prefer semantic IDs such as
  `slide-03-alert-chart` and `slide-03-alert-title`; never use `""`, array
  indexes alone, timestamps, or random UUIDs.
- Text `content` is the canonical rich-text source shared by the browser
  preview and PPTX export. Use only the safe HTML subset
  `<p><span><strong><em><u><br>` and put typography in inline CSS, for example:
  `<p><span style="font-size: 42px; font-weight: 700; color: #023047">Title</span></p>`.
  Do not put `fontSize` only in an unused `richText` field.
- Use `<br>` or separate `<p>` elements for line breaks. Do not put raw `\n`
  characters in HTML content.
- Save the complete artifact as
  `/workspace/artifacts/deck.slides.json`.
- Save only `{ "slides": [ ... ] }`; do not paste the full JSON into chat.

## Included Validation Script

The skill ships with a standard-library validator:

```bash
python3 /opt/castrel/skills/builtin/pptx-generator/scripts/validate_slides.py \
  /workspace/artifacts/deck.slides.json
```

The validator checks JSON structure, canvas bounds, duplicate IDs, safe text
markup, required text font sizes, chart/table shape, page badges, text density,
and repeated layouts. Structural and security findings are errors. Visual
quality findings are warnings during iteration. During normal generation, use `--json` without `--strict`; warnings are
feedback and must not trigger a full-deck regeneration. Use `--strict` only
when a zero-warning local review is explicitly required:

```bash
python3 /opt/castrel/skills/builtin/pptx-generator/scripts/validate_slides.py \
  /workspace/artifacts/deck.slides.json --strict
```

Use `--json` when a machine-readable report is useful. This validator is local
feedback only: the backend `write_artifact` call (with `format="slides_ir"`) is
the authoritative save gate. Backend structural/security errors block
persistence; visual findings are returned as warnings and do not require
rewriting an otherwise valid deck.

## Persisting the Deck

Persist the deck by calling the platform `write_artifact` tool with
`format="slides_ir"`, `client_id="<proxy client id>"`, and
`sandbox_file="/artifacts/deck.slides.json"` (the logical sandbox path). Do NOT
pass the JSON body as `content` — the backend reads the file straight from the
sandbox over the bridge, validates the slide IR, and stores the metadata in
`agent_artifact` + `documents` with the JSON block in object storage (MinIO).
There is no separate `save_slides_artifact` tool.

To overwrite an existing deck (a re-edit), pass the existing `artifact_id`
alongside the same `sandbox_file` so the backend appends a new document version
instead of creating a new artifact.

## Incremental Editing

Generate the complete deck once. For subsequent visual or content fixes, edit
the local sandbox file `/workspace/artifacts/deck.slides.json` in place with the
`patch_slides.py` helper (or a small `python3` edit), preserving stable element
IDs and touching only the affected elements. Do not send the complete JSON
through a tool call.

Use `--set-id` for stable-element-ID edits:

```bash
python3 /opt/castrel/skills/builtin/pptx-generator/scripts/patch_slides.py \
  /workspace/artifacts/deck.slides.json \
  --set-id slide-03-title content \
  '<p><span style="font-size: 34px">Updated title</span></p>'
```

Use `--operation` with JSON Pointer paths for array edits:

```bash
python3 /opt/castrel/skills/builtin/pptx-generator/scripts/patch_slides.py \
  /workspace/artifacts/deck.slides.json \
  --operation '{"op":"replace","path":"/slides/2/elements/4/left","value":680}'
```

Use `--remove-id` to delete an element by its stable ID. Keep edits small,
preserve unrelated IDs, then call `write_artifact` again (with `artifact_id`) to
validate and persist the new version. If the backend returns validation errors,
fix only the reported paths and retry; do not regenerate the entire deck.

## Execution Contract: Python, Shapes, and Validation

Follow this contract exactly. Do not infer an alternative schema from PPT,
SVG, PPTist, or PowerPoint examples.

### Python interpreter

- For `execute_castrel_proxy_sandbox`, pass `language: "python3"` for Python
  scripts.
- In a Bash script inside the sandbox, invoke `python3`, never `python`.
- The standard library is available; do not install packages or use network
  access for deck generation.

### Shape elements

Castrel does not support a `rect` element type. A rectangle is a `shape` whose
path is drawn inside a matching `viewBox`. Every shape must contain all of
these fields:

```python
def shape(element_id, left, top, width, height, fill):
    return {
        "type": "shape",
        "id": element_id,
        "left": left,
        "top": top,
        "width": width,
        "height": height,
        "viewBox": [width, height],
        "path": f"M 0 0 L {width} 0 L {width} {height} L 0 {height} Z",
        "fill": fill,
    }
```

Use the helper directly, for example:

```python
shape("slide-01-accent", 720, 130, 180, 180, "#219ebc")
```

Do not use `{"type": "rect"}`, omit `left`/`top`/`width`/`height`, leave
`viewBox` or `path` out, or wrap an element with `dict(element, {...})`.
Assign stable IDs at creation time; never leave an empty ID for a later pass.

### Validation command

Use this command for local structural feedback when useful:

```bash
python3 /opt/castrel/skills/builtin/pptx-generator/scripts/validate_slides.py \
  /workspace/artifacts/deck.slides.json --strict --json
status=$?
printf 'VALIDATION_EXIT=%s\n' "$status"
exit "$status"
```

The final `exit "$status"` is required; without it, a trailing `echo` can hide
validation failures from the tool result. For local structural errors, fix
only the reported JSON paths. Visual warnings may be reviewed and left for
the backend save response instead of triggering a full-deck rewrite.

## Seven-Step Design Workflow

### Step 1: Research and Requirements

Understand the topic, audience, purpose, tone, content depth, and expected
action. Identify the essential message before selecting layouts.

### Step 2: Select a Color Palette and Fonts

Choose one coherent five-color theme:

| Theme key | Role |
|-----------|------|
| `primary` | Titles and strongest visual anchor |
| `secondary` | Body text and dark supporting elements |
| `accent` | Focus, status, and visual emphasis |
| `light` | Secondary surfaces and subtle accents |
| `bg` | Slide background |

Recommended palette examples:

| Palette | `primary` | `secondary` | `accent` | `light` | `bg` |
|---------|-----------|-------------|----------|---------|------|
| Modern & Wellness | `#006d77` | `#83c5be` | `#e29578` | `#ffddd2` | `#edf6f9` |
| Business & Authority | `#2b2d42` | `#8d99ae` | `#ef233c` | `#edf2f4` | `#d90429` |
| Nature & Outdoors | `#283618` | `#606c38` | `#bc6c25` | `#dda15e` | `#fefae0` |
| Vibrant & Tech | `#023047` | `#219ebc` | `#fb8500` | `#ffb703` | `#8ecae6` |
| Education & Charts | `#264653` | `#2a9d8f` | `#e76f51` | `#e9c46a` | `#f4a261` |
| Platinum White Gold | `#0a0a0a` | `#0070F3` | `#D4AF37` | `#f5f5f5` | `#ffffff` |

Use Microsoft YaHei for Chinese and Arial by default for English. Choose an
approved pairing when the subject benefits from a more distinctive header font.

### Step 3: Select a Visual Style

Choose one style recipe and apply it consistently:

- **Sharp**: geometric, compact, formal, and information-dense.
- **Soft**: balanced spacing and moderate rounding for general business use.
- **Rounded**: generous whitespace and friendly modern surfaces.
- **Pill**: open spacing, strong brand presence, and full rounded treatments.

Recommended style parameters:

| Style | Corner radius | Element gap | Page margin |
|-------|---------------|-------------|-------------|
| Sharp | `0–5px` | `16–24px` | `60px` |
| Soft | `5–12px` | `24–40px` | `60px` |
| Rounded | `12–25px` | `32–50px` | `60px` |
| Pill | Up to half the element height | `40–60px` | `60px` |

Do not mix unrelated corner radii or spacing systems on the same deck.

### Step 4: Plan the Slide Outline

Classify every slide as exactly one of the five page types:

1. Cover Page
2. Table of Contents
3. Section Divider
4. Content Page
5. Summary / Closing Page

For each Content Page, select exactly one subtype: Text, Mixed Media, Data
Visualization, Comparison, Timeline / Process, or Image Showcase.

Plan visual variety before writing JSON. Do not use the same composition on
consecutive slides.

### Step 5: Generate the Slide IR JSON

Create the deck as one complete JSON document. Map design decisions to schema
fields:

- Slide background -> `background.color`.
- Shape surfaces -> `fill` and the schema's shape radius/line fields.
- Text hierarchy -> `font-size` in the HTML `content` style fields. The
  renderer and exporter must receive the same styled content.
- Theme colors -> `defaultColor`, text color, fills, and `themeColors`.
- Layout -> absolute `left`, `top`, `width`, and `height`.
- Visual identity -> stable semantic IDs such as `slide-03-title`.

Use a safe page margin near `60px`. Keep all right and bottom edges inside
`1000 × 562.5`.

### Step 6: Perform QA

Assume the first render has problems. Run the included validator first, then
inspect the SlideRenderer preview. Check content completeness, stable IDs,
canvas bounds, text overflow, overlap, contrast, alignment, spacing, page
numbers, and layout variety. Remove placeholder text and correct issues
without changing unrelated IDs. Inspect the affected slides again after each
fix.

The required loop is:

1. Generate the complete JSON once in a `python3` sandbox call, using the shape
   contract above.
2. Run local validation with `--json` when useful and fix structural/security errors.
3. Preview the deck and inspect each slide at readable scale.
4. Apply visual or content fixes by editing the local sandbox file with
   `patch_slides.py`, preserving unrelated IDs and changing only affected
   elements.
5. Call `write_artifact` (`format="slides_ir"`, `sandbox_file=...`, plus
   `artifact_id` when overwriting); the backend performs the final structural
   and security validation before persistence.
6. If the save response contains validation errors, fix only those paths and
   call `write_artifact` again. Treat visual findings as warnings unless the
   user asks for further polish.

The validator is a quality gate, not a substitute for visual inspection. A
passing deck can still be visually weak if it uses repetitive layouts or
unfocused copy.

### Step 7: Save the Artifact

Write the complete initial JSON to:

`/workspace/artifacts/deck.slides.json`

## Theme Contract

Use these exact conceptual keys for every deck:

| Key | Purpose |
|-----|---------|
| `primary` | Darkest title and anchor color |
| `secondary` | Supporting dark color |
| `accent` | Mid-tone focal color |
| `light` | Light accent and surface color |
| `bg` | Background color |

Use only colors from the selected palette. Do not invent, blend, brighten, or
darken colors. Use an explicit transparency field only when the schema
supports it. Gradients and animations are not allowed.

## Typography Contract

Use this hierarchy as a starting point and adjust only for content density:

| Usage | Recommended size |
|-------|------------------|
| Annotation / source | 12–14px |
| Body / description | 16–20px |
| Subtitle | 22–28px |
| Section heading | 28–36px |
| Slide title | 40–48px |
| Cover / section title | 60–80px |
| Data callout | 72–96px |

Titles and headings may be bold. Body, caption, legend, and source text should
remain regular weight. Left-align paragraphs and lists; center only titles or
short focal statements.

## Layout Contract

Use the following coordinate guidance on the `1000 × 562.5` canvas:

| Zone | Guidance |
|------|----------|
| Safe margin | About `60px` on every side |
| Header zone | `top: 60–120px` |
| Main content | `top: 150–470px` |
| Footer / page badge | Keep inside the bottom `60px` margin |
| Column gap | `24–40px` |
| Card padding | `20–40px` |
| Major block gap | `50–80px` |

Use equal widths and consistent baselines for grids, columns, and repeated
rows. Every Content Page must contain at least one visual element besides text.

## Five Page Types

### 1. Cover Page

Use for opening and tone setting. Include a required main title, optional
subtitle and metadata, and a strong visual or background motif.

- Asymmetric left-right: text on one side and a visual on the other.
- Center-aligned: title and subtitle over a restrained background.
- Main title: 60–80px; subtitle: 24–32px; metadata: 12–16px.
- Make the title at least twice the subtitle size.
- Do not add a page number badge to the cover.

### 2. Table of Contents

Use for navigation and expectation setting, usually with three to six
sections.

- Numbered vertical list for three to five sections.
- Two-column grid for four to six sections.
- Sidebar navigation for a compact corporate deck.
- Card-based layout for a modern or creative deck.
- Page title: 36–44px; section number: 28–36px; section title: 20–28px.
- Include a page number badge.

### 3. Section Divider

Use for a clear transition between major parts. Include a required section
number and title, with an optional one- or two-line introduction.

- Bold center for a minimal presentation.
- Accent block for a structured corporate presentation.
- Split background for a high-contrast transition.
- Section number: 60–80px; title: 36–48px; intro: 16–20px.
- Leave generous whitespace and include a page number badge.

### 4. Content Page

Choose exactly one subtype:

- **Text**: bullets, quote, or short paragraphs plus an icon or shape.
- **Mixed Media**: text column plus image or visual column.
- **Data Visualization**: chart, source, and takeaways.
- **Comparison**: side-by-side columns or cards.
- **Timeline / Process**: numbered steps and directional connectors.
- **Image Showcase**: hero visual and caption.

Use a required slide title, left-align body text, and include a visual element.
Use 40–48px titles, 16–20px body text, and 12–14px captions. Include a page
number badge.

For a five-slide deck, a reliable visual progression is:

1. Cover: asymmetric title plus one restrained visual motif.
2. Context: one clear thesis with a comparison or three-part visual.
3. Capability: a matrix, architecture, or workflow instead of another card
   grid.
4. Detail: a timeline, process diagram, or chart with one takeaway.
5. Closing: a concise recap, security/value proof, and next action.

Avoid using the same card grid on consecutive slides. Each content slide should
have one dominant visual idea; do not fill the canvas with equally weighted
boxes.

### 5. Summary / Closing Page

Use for wrap-up and action. Choose a key-takeaway list, CTA / next steps,
thank-you / contact, or split recap.

- Closing title: 48–64px.
- Takeaways and actions: 20–28px, concise and scannable.
- Keep contact information legible but secondary.
- Match the energy and palette of the cover.
- Include a page number badge.

## Page Number Badge

Every slide except the Cover Page must include one stable page-number element
near the bottom-right of the safe area. Show only the current page number, keep
it subtle, and use palette colors. The badge may be a circle, pill, or compact
text treatment consistent with the selected style.

## Re-Edit Workflow

1. Read the current `slides_ir` artifact from
   `/workspace/artifacts/deck.slides.json`.
2. Identify the target slide and semantic element IDs.
3. Preserve the theme, page type, and existing IDs.
4. Use `patch_slides.py` to change only requested content, style, or geometry
   fields.
5. Remove complete obsolete elements instead of clearing their content.
6. Give new elements deterministic IDs derived from slide and semantic role.
7. Re-run the QA checklist and save the complete artifact.

Represent list items, steps, and cards as separate elements when they need
independent editing. Never replace a multi-item structure with an opaque text
blob.
