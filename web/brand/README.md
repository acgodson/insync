# InSync brand

The mark: two short rounded sound bars rise into the four fingers of an open hand, with a tilted
thumb. Spoken words (blue) and signing (amber) in one gesture. Solid shapes only, no strokes, so it
still reads at 16 px. Reference board: `team-mark-reference.jpg`.

## Palette

| Name        | Hex       | Use                                                     |
|-------------|-----------|---------------------------------------------------------|
| Forest      | `#1E2B1C` | hand on light backgrounds, light-version wordmark       |
| Sage        | `#D3DCC2` | deck / light background                                 |
| Moss        | `#6F8A5C` | sound bars on light backgrounds                         |
| Ink         | `#111111` | product dark, app icon and favicon tile, `theme-color`  |
| Voice blue  | `#8EC5E8` | sound bars on dark (the speaker colour)                 |
| Sign amber  | `#E9B84E` | thumb (the signer colour)                               |
| Paper       | `#F3F3EE` | hand and wordmark on dark                               |

Type: Inter SemiBold (600) for the product wordmark, lowercase `insync`; fallbacks
Atkinson Hyperlegible, system-ui. (The deck uses Newsreader; not needed in the product.)

## Files

| File | What |
|------|------|
| `insync-mark.svg` | mark only, square, reversed colours for dark backgrounds |
| `insync-mark-light.svg` | mark only, for light backgrounds (moss bars, forest hand, amber thumb) |
| `insync-mark-mono-white.svg` | single-colour white mark |
| `insync-lockup.svg` | mark + `insync` wordmark for dark backgrounds, live `<text>` (Inter 600 with fallbacks) |
| `insync-lockup-outlined.svg` | same, wordmark converted to paths (no font needed); use this when embedding |
| `insync-lockup-light.svg` | outlined lockup for light backgrounds |
| `favicon.svg`, `favicon-32.png` | Ink rounded tile with the reversed mark |
| `icon.svg`, `icon-1024.png` | app icon: Ink rounded square, all-white mark |
| `build_brand.py` | regenerates everything above, plus `app/assets/brand/insync-mark.png` (512 px) and the Android `mipmap-*/ic_launcher.png` (48–192 px) |
| `apply_brand.py` | brands the built signer UI `web/dist/index.html` (see below) |
| `apply_brand.targets.txt` | every `InSync` occurrence in `web/dist/index.html`, marked CHANGE or keep |

Geometry (in `build_brand.py`) is measured from the reference at 1 unit = 1 reference pixel:
mark box 164 × 124, bars and fingers 17 wide with 5 gaps, palm corner radius 20, thumb a
17-wide capsule at about 55°. In the lockup the wordmark x-height is half the mark height and the
`insync` ink width is 325 units, as on the reference board. Outlining uses fontTools on
Inter-SemiBold.ttf (set `$INTER_TTF` if it lives somewhere else).

Usage: keep clear space of one finger width around the mark; minimum size 16 px for the mark,
20 px high for the lockup. Do not recolour the bars and thumb independently of the palette above,
outline the shapes, or set the wordmark in another weight.

## Where it is used

- `backend/static/join.html`: header wordmark replaced by the inline outlined lockup (22 px high);
  favicon added as an SVG data URI `<link rel="icon">`. The "InSync" title on the name card is
  unchanged.
- `app/`: Android launcher icons; splash shows `assets/brand/insync-mark.png` above "InSync".
- `README.md`: lockup at the top (dark/light variants via `#gh-dark-mode-only` / `#gh-light-mode-only`).

## `apply_brand.py` (web/dist/index.html)

```
python3 web/brand/apply_brand.py [--dry-run] [path/to/index.html]   # default web/dist/index.html
```

It changes exactly:

1. Landing header `<div class="brand"><svg class="mark"><use href="#i-mark" /></svg><span>InSync</span></div>`
   becomes `<div class="brand" data-insync-brand="landing">` with the inline outlined lockup, 22 px high.
2. Room top bar `<svg class="mark" aria-label="InSync"><use href="#i-mark" /></svg>` (signer and
   participant `/join/CODE` views share it) becomes the inline colour hand mark,
   `data-insync-brand="room"`, 22 px high.
3. `<link rel="icon">`: inserted after `<title>` (or replaced if one exists) with the favicon data URI,
   tagged `data-insync-favicon`.
4. `<meta name="theme-color">` set to `#111111` (was `#0f0f10`).

Not changed: `<title>`, the old `#i-mark` symbol (left in place, now unused), and every `InSync` in body
copy or script strings. The join/start screen has no brand element. Safe to run twice: each edit
whose marker is already present and whose anchor is gone is skipped. If an anchor appears more than
once, or neither the anchor nor its marker is found, it writes nothing, prints which one and exits 2.
