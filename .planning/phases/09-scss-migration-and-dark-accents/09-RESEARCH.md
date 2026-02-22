# Phase 9: SCSS Migration and Dark Accents - Research

**Researched:** 2026-02-22
**Domain:** Odoo SCSS variable system, dark mode bundle architecture, CSS migration
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Light mode appearance**
- Blend fully with Odoo's standard light UI — no custom "dev tool" identity in light mode
- All panels (sidebar, header, detail) use the same light background; borders alone define separation (no subtle depth differences between panels)
- Tree row selection should follow Odoo's standard list view selection style, not the current 3px left-border accent
- Code block backgrounds (JSON viewer, text previews, diff snapshots): Claude's discretion based on readability

**Dark syntax palette**
- Match Odoo's own code editor / ace editor color scheme for dark mode syntax highlighting (JSON keys, strings, numbers, booleans)
- Light mode syntax colors: Claude's discretion — pick what reads best on the light background
- Null/undefined visual treatment: Claude's discretion
- Interactive element hover/active colors (JSON toggles, truncation links): Claude's discretion

**Status & diff colors**
- Status mapping: Running = `$o-action`, Paused = `$o-warning`, Done = `$o-success`, Error = `$o-danger`
- Connection dot: Connected = `$o-success`, Disconnected = `$o-danger`
- Tree row status icons: Same semantic mapping — checkmark = `$o-success`, X = `$o-danger`, pause = `$o-warning`
- Diff tint opacity: Claude's discretion — adjust per mode for best readability
- Error/warning banners: Use Odoo's standard Bootstrap alert component styling (`.alert-danger`, etc.) instead of custom tinted backgrounds

**Component cleanup**
- Notebook tab overrides (`.ai-debug-detail .o_notebook` block): Strip entirely, trust Odoo enterprise SCSS for dark mode
- Dialog overrides (`.o_dialog` block including `filter: invert(1)` hack): Strip entirely, trust Bootstrap `--bs-modal-bg`
- Popup content (`.ai-popup-content` block): Strip entirely, let dialog content use default styling
- CopyButton overrides (`.ai-detail-section-header .o_clipboard_button` block): Strip entirely, use Odoo's default CopyButton styling

### Claude's Discretion
- Code block background treatment in light mode
- Light mode syntax highlighting color palette
- JSON null/undefined visual treatment
- Interactive element hover colors
- Diff tint opacity per mode
- Any remaining visual polish decisions not explicitly locked above

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SCSS-01 | All hardcoded background colors in `app.scss` replaced with `$o-gray-*` SCSS variables | Color mapping table below; `$o-webclient-background-color` and `$o-view-background-color` for panel backgrounds |
| SCSS-02 | All hardcoded border colors in `app.scss` replaced with SCSS variables | Use `$border-color` (auto-dark-aware via `$o-gray-300`) or `$o-gray-*` directly |
| SCSS-03 | All hardcoded text colors in `app.scss` replaced with SCSS variables | Map Catppuccin text values to `$o-gray-600` through `$o-gray-900` for light/dark aware text |
| SCSS-04 | All hardcoded accent colors (success, error, warning, info) replaced with `$o-success`, `$o-danger`, `$o-warning`, `$o-action` | Status mapping confirmed; semantic vars exist in both light and dark |
| SCSS-05 | All hardcoded `rgba()` values audited and replaced with theme-aware equivalents | rgba values map to: diff tints → `rgba($o-success/danger/warning, opacity)`, flash animation → `rgba($o-action, opacity)`, ancestor hover → `rgba($o-action, 0.05)` |
| COMP-01 | Notebook component override block removed from `app.scss` | Enterprise `notebook.dark.scss` + `notebook.scss` handle dark mode natively via CSS variables; safe to delete entire `.ai-debug-detail .o_notebook` block |
| COMP-02 | Dialog component override block removed from `app.scss` | `$modal-content-bg` is set to `$o-view-background-color` which auto-adapts; Bootstrap handles btn-close in dark mode; safe to delete entire `.o_dialog` block |
| DARK-01 | `app.dark.scss` created with dark-mode-specific accent colors for syntax highlighting | Pattern: use `$o-*` variables from dark primary_variables; manifest needs explicit ordering after `web.dark_mode_variables`; file needs to be excluded from light bundle |
| DARK-02 | Status badge colors verified and adjusted for both light and dark modes | All semantic vars differ by mode automatically; the pulse dot color needs to use `$o-gray-500` not hardcoded Catppuccin |
</phase_requirements>

---

## Summary

The app currently uses 100% hardcoded Catppuccin Mocha hex values, all calibrated for dark mode only. Migrating to Odoo's SCSS variable system means the light bundle compiles with light values and the dark bundle compiles with dark values — the same `app.scss` source serves both, with no runtime JavaScript required.

The Odoo variable hierarchy is: `primary_variables.scss` (base web defaults) → `web_enterprise/primary_variables.scss` (enterprise light overrides) → `web_enterprise/primary_variables.dark.scss` (dark overrides injected at compile time by `web.dark_mode_variables`). Since `ai_debug.assets_dark` already includes `web.dark_mode_variables`, any SCSS compiled in that bundle sees the dark values.

Two manifest changes are required: (1) `app.dark.scss` must be **excluded** from the light `ai_debug.assets` bundle and added **after** `web.dark_mode_variables` in `ai_debug.assets_dark`, matching the enterprise `*.dark.scss` pattern. (2) The error banner must change from a custom rgba background to Odoo's `.alert-danger` / `.alert-warning` Bootstrap component classes (applied in the XML template, not SCSS).

**Primary recommendation:** Replace every hardcoded hex/rgba with the `$o-gray-*` / semantic variable equivalents, delete the four dead override blocks (Notebook, Dialog, popup content, CopyButton), create `app.dark.scss` for syntax-only dark accents, and update the manifest to exclude dark SCSS from the light bundle.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Odoo SCSS variable system | Master | Theme-aware colors | Compiled at bundle time; single source of truth for light/dark |
| Bootstrap 5 (via Odoo) | BS5 | Component styling, modal, alerts | Already included; `.alert-danger`, `--bs-modal-bg` work automatically |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `web.dark_mode_variables` | Master | Dark variable injection | Already included in `ai_debug.assets_dark`; no changes needed there |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `$o-gray-*` SCSS vars | CSS custom properties (`--bs-*`) | CSS custom props are NOT emitted by Odoo when `$enable-dark-mode: false`; use SCSS vars always |
| `.alert-danger` component | Custom rgba banner | Custom rgba doesn't adapt to light mode (too bright); Bootstrap alerts are already dark-mode-aware |

---

## Architecture Patterns

### Recommended File Structure

```
ai_debug/static/src/app/
├── app.scss           # All styles using $o-* variables (light AND dark compile from this)
└── app.dark.scss      # Dark-only overrides: syntax highlight colors, anything that needs
                       # explicit dark values beyond what variable substitution gives
```

### Pattern 1: Variable-Only Replacement

**What:** Replace hardcoded colors with `$o-gray-*` or semantic variables. The same line compiles to different hex values in light vs. dark bundles.

**When to use:** All backgrounds, borders, and text — the majority of the migration.

**Example:**
```scss
// Before (hardcoded dark):
background-color: #1e1e2e;
border: 1px solid #313244;
color: #cdd6f4;

// After (variable-driven):
background-color: $o-webclient-background-color;
border: 1px solid $border-color;
color: $o-gray-900;
```

Light compiles to: `background-color: #F9FAFB; border: 1px solid #d8dadd; color: #111827`
Dark compiles to: `background-color: #1B1D26; border: 1px solid #3C3E4B; color: #E4E4E4`

### Pattern 2: Dark-Only File for Syntax Colors

**What:** `app.dark.scss` holds only colors that have no meaningful light equivalent — JSON syntax highlighting, because the Catppuccin palette for code has no matching Odoo semantic equivalent.

**When to use:** Accent colors that exist only in dark context (syntax palette). Do NOT put structural layout here.

**Example:**
```scss
// app.dark.scss — only compiled in the dark bundle
.ai-json-key    { color: $o-action; }         // #02c7b5 in dark (teal)
.ai-json-string { color: $o-success; }        // #1dc959 in dark (green)
.ai-json-number { color: $o-warning; }        // #FBB56A in dark (peach/amber)
.ai-json-boolean { color: $o-main-code-color; } // #c58bc8 in dark (mauve)
.ai-json-null   { color: $o-gray-500; font-style: italic; }
```

### Pattern 3: Manifest Ordering for Dark SCSS

**What:** `.dark.scss` files must be excluded from the light bundle and added AFTER variable injection in the dark bundle.

**When to use:** Any time a `*.dark.scss` file is created in the project.

**Manifest pattern (verified from web_enterprise and web_gantt):**
```python
'ai_debug.assets': [
    ('include', 'web.assets_backend'),
    ('remove', 'ai_debug/static/src/app/**/*.dark.scss'),  # ADD THIS
    'ai_debug/static/src/app/**/*.scss',
    'ai_debug/static/src/app/**/*.xml',
    'ai_debug/static/src/app/**/*.js',
],
'ai_debug.assets_dark': [
    ('include', 'ai_debug.assets'),
    ('include', 'web.dark_mode_variables'),
    'ai_debug/static/src/app/**/*.dark.scss',  # ADD THIS — after variable injection
],
```

**Critical:** The `('remove', ...)` must come BEFORE the `'**/*.scss'` glob in `ai_debug.assets`. The `'**/*.dark.scss'` addition in `ai_debug.assets_dark` must come AFTER `('include', 'web.dark_mode_variables')`.

### Pattern 4: Selection Highlighting (replacing 3px border accent)

**What:** Odoo list view uses `$o-component-active-bg` (a mix of `$o-action` and `$o-gray-100`) for selected row backgrounds — no left border.

**When to use:** Replacing the current `border-left: 3px solid #89b4fa` on `.ai-tree-row.selected`.

**Example:**
```scss
&.selected {
    background-color: $o-component-active-bg;
    // No border-left — matches Odoo's list view pattern
    animation: none;
}
```

`$o-component-active-bg` in light = `mix($o-action, $o-gray-100, 10%)` = light teal tint.
`$o-component-active-bg` in dark = `mix($o-action, $o-gray-300, 10%)` = dark surface with action tint.

### Anti-Patterns to Avoid

- **CSS custom properties for theming:** `--bs-*` variables are not reliably emitted in Odoo's SCSS compilation when `$enable-dark-mode: false`. Use `$o-*` SCSS variables always.
- **Keeping the `filter: invert(1)` hack:** The `.btn-close` in Bootstrap 5 automatically inverts in dark mode through `$btn-close-color` which Odoo's dark bootstrap override sets correctly. The entire `.o_dialog` block should be deleted.
- **Putting layout overrides in `app.dark.scss`:** Only color overrides belong there. Layout, sizing, spacing should be in `app.scss` and use variables.
- **Using `mix()` or `lighten()`/`darken()` on hardcoded colors:** Always mix against `$o-gray-*` or semantic variables so dark mode benefits.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Error banners | Custom rgba background styling | `.alert-danger`, `.alert-warning` Bootstrap classes in XML | Bootstrap alerts handle both light/dark automatically; custom rgba is light-mode-unreadable |
| Notebook dark tabs | `.ai-debug-detail .o_notebook` override block | Delete entirely — enterprise `notebook.dark.scss` handles it | Enterprise applies CSS variables that adapt at compile time |
| Dialog dark styling | `.o_dialog` override block with `filter: invert(1)` | Delete entirely — `$modal-content-bg: $o-view-background-color` handles it | Bootstrap's `$modal-content-bg` variable adapts to dark mode via variable chain |

**Key insight:** Enterprise Odoo pre-solves dark mode for its own components. The migration goal is to REMOVE custom overrides that were fighting Odoo, not to add new ones.

---

## Common Pitfalls

### Pitfall 1: Wrong Variable for "Darkest" Background

**What goes wrong:** Developer uses `$o-gray-100` thinking it's light, but in dark mode `$o-gray-100` IS the darkest color (#1B1D26). The scale is inverted.

**Why it happens:** The `!default` overrides in `primary_variables.dark.scss` fully redefine the gray scale. `$o-gray-100` becomes the darkest background, `$o-gray-900` becomes near-white text.

**How to avoid:** Think semantically: `$o-webclient-background-color` = outermost background (sidebar, app shell). `$o-view-background-color` = content area background (detail panel). These always resolve correctly regardless of mode.

**Mapping:**
```
Catppuccin base (#1e1e2e) → $o-webclient-background-color
Catppuccin mantle (#181825) → $o-gray-100 (in dark; lightest section header bg)
Catppuccin crust (#11111b) → $o-view-background-color (in dark: $o-gray-200)
```

### Pitfall 2: app.dark.scss Loading Before Variables

**What goes wrong:** `app.dark.scss` compiles with light variable values because it's included via the glob before `web.dark_mode_variables` is injected.

**Why it happens:** The glob `'ai_debug/static/src/app/**/*.scss'` in `ai_debug.assets` loads ALL scss files alphabetically. `app.dark.scss` sorts before `app.scss`. If the dark bundle just includes the light bundle wholesale without explicit ordering, dark files compile with wrong values.

**How to avoid:** Use the `('remove', ...)` + explicit re-add pattern from Pattern 3 above. The `('remove', 'ai_debug/static/src/app/**/*.dark.scss')` in `ai_debug.assets` and explicit addition in `ai_debug.assets_dark` AFTER `web.dark_mode_variables`.

### Pitfall 3: Syntax Colors in app.scss Instead of app.dark.scss

**What goes wrong:** JSON syntax colors set in `app.scss` using dark Catppuccin colors look wrong in light mode (e.g., `#89b4fa` blue key on white background is fine, but `#fab387` peach number color is ugly in light).

**Why it happens:** These are aesthetic accent colors with no direct Odoo semantic equivalent — they're visual language, not state communication.

**How to avoid:**
- In `app.scss`: set light mode syntax colors (claude's discretion — e.g., `$o-action` for keys)
- In `app.dark.scss`: override with dark-specific values matching Odoo's ace editor palette

### Pitfall 4: rgba() with Hardcoded Catppuccin Color Arguments

**What goes wrong:** `rgba(137, 180, 250, 0.3)` in a flash animation uses Catppuccin blue, which stays hardcoded even after migrating the solid colors.

**Why it happens:** rgba() calls are easy to overlook in keyword grep for hex values.

**How to avoid:** Search specifically with `grep -n "rgba("` and replace each one:
- `rgba(137, 180, 250, 0.3)` (Catppuccin blue flash) → `rgba($o-action, 0.3)`
- `rgba(137, 180, 250, 0.05)` (ancestor hover) → `rgba($o-action, 0.05)`
- `rgba(166, 227, 161, 0.1)` (diff added) → `rgba($o-success, 0.1)`
- `rgba(243, 139, 168, 0.1)` (diff removed / error banner) → `rgba($o-danger, 0.1)`
- `rgba(249, 226, 175, 0.1)` (diff changed) → `rgba($o-warning, 0.1)`
- `rgba(243, 139, 168, 0.3)` (error banner border) → `rgba($o-danger, 0.3)` — but this whole banner block will be replaced by `.alert-danger`

### Pitfall 5: Light Mode Panels Need a Flat Appearance

**What goes wrong:** Different `$o-gray-*` levels for sidebar vs. header vs. detail panel create a subtle depth that looks intentional in dark mode but awkward in light mode (the "dev tool" look the user specifically rejected).

**Why it happens:** The natural instinct is to differentiate panels. In light mode, the Odoo standard uses borders for separation, not background depth.

**How to avoid:** Per CONTEXT.md locked decision: all panels use the same background. Use `$o-webclient-background-color` for the app container, sidebar, and header. Use `$o-view-background-color` for the detail content area (just the scrollable content body, not the entire panel).

---

## Code Examples

### Complete Catppuccin → Odoo Variable Mapping

Verified by comparing app.scss hex values against `primary_variables.scss` (web + enterprise) and `primary_variables.dark.scss`:

```scss
// === BACKGROUNDS ===
// #1e1e2e (Base) → app container, sidebar, header
background-color: $o-webclient-background-color;
// Light resolves: $o-gray-100 = #F9FAFB (enterprise)
// Dark resolves: $o-gray-100 = #1B1D26

// #11111b (Crust) → detail panel content area
background-color: $o-view-background-color;
// Light resolves: white
// Dark resolves: $o-gray-200 = #262A36

// #181825 (Mantle) → code blocks, secondary headers, diff headers
// No exact semantic var — use $o-gray-100 in dark context, handled by:
background-color: $o-webclient-background-color; // same as outer shell

// === BORDERS ===
// #313244 (Surface0) → most borders
border-color: $border-color; // = $o-gray-300
// Light: #d8dadd (enterprise), Dark: #3C3E4B

// #181825 (Mantle) → subtle section dividers
border-color: $o-gray-200;
// Light: #e7e9ed, Dark: #262A36

// === TEXT ===
// #cdd6f4 (Text) → primary text
color: $o-gray-900;
// Light: #111827, Dark: #E4E4E4

// #a6adc8 (Subtext0) → secondary text, monospace content
color: $o-gray-700;
// Light: #374151, Dark: #B1B3BC

// #6c7086 (Overlay0) → subtle labels, section headers
color: $o-gray-600;
// Light: #5f636f (web), Dark: #7E8392

// #585b70 (Surface2) → very muted/dim text, placeholders
color: $o-gray-500;
// Light: #7c7f89 (web), Dark: #6B707F

// #45475a (Surface1) → hints (even dimmer)
color: $o-gray-400;
// Light: #9a9ca5 (enterprise), Dark: #5A5E6B

// === SEMANTIC (ACCENTS) ===
// #89b4fa (Catppuccin Blue) → action/accent
color: $o-action;
// Light: #017e84 (teal), Dark: #02c7b5 (bright teal)

// #a6e3a1 (Catppuccin Green) → success
color: $o-success;
// Light: #28a745, Dark: #1dc959

// #f38ba8 (Catppuccin Red) → danger/error
color: $o-danger;
// Light: #dc3545, Dark: #b83232

// #f9e2af (Catppuccin Yellow) → warning
color: $o-warning;
// Light: #ffac00, Dark: #FBB56A

// === INTERACTIVE STATES ===
// #2d3748 (selected row bg) — no Catppuccin name, custom bluish
background-color: $o-component-active-bg;
// Light: mix($o-action, $o-gray-100, 10%) = very light teal tint
// Dark: mix($o-action, $o-gray-300, 10%)

// #2a2a3e (hover row bg)
background-color: $o-gray-200;
// Light: #e7e9ed (light gray hover), Dark: #262A36 (dark hover)
```

### Syntax Highlight Colors for app.dark.scss

Based on Odoo's `$o-main-code-color` and ace editor patterns, using available dark variables:

```scss
// app.dark.scss
// Source: web_enterprise/static/src/scss/primary_variables.dark.scss values

// JSON key (was #89b4fa Catppuccin Blue)
.ai-json-key    { color: $o-action; }         // #02c7b5 in dark — teal, distinct

// JSON string (was #a6e3a1 Catppuccin Green)
.ai-json-string { color: $o-success; }        // #1dc959 in dark — green, legible

// JSON number (was #fab387 Catppuccin Peach) — no direct semantic equiv
// $o-warning (#FBB56A) is closest warm tone
.ai-json-number { color: $o-warning; }        // #FBB56A in dark — amber/peach

// JSON boolean (was #cba6f7 Catppuccin Mauve) — matches $o-main-code-color
.ai-json-boolean { color: $o-main-code-color; } // #c58bc8 in dark — mauve

// JSON null/undefined (was #585b70)
.ai-json-null { color: $o-gray-500; font-style: italic; } // dim, clearly absent value
```

### Error Banner Migration (XML + SCSS change)

Per locked decision, error banners must use Odoo Bootstrap alert classes:

**Current SCSS (DELETE):**
```scss
.ai-detail-error-banner {
    padding: 8px 16px;
    background-color: rgba(243, 139, 168, 0.1);
    border-bottom: 1px solid rgba(243, 139, 168, 0.3);
    color: #f38ba8;
    font-size: 13px;
    span:first-child { font-weight: 600; }
}
```

**Replacement approach:** In the XML template, change the custom class to use Bootstrap alert classes. The SCSS class `.ai-detail-error-banner` gets deleted entirely.

```xml
<!-- Before -->
<div class="ai-detail-error-banner" t-if="hasError">
    <span>Error:</span> <t t-esc="errorMessage"/>
</div>

<!-- After -->
<div class="alert alert-danger mb-0 rounded-0 border-start-0 border-end-0" t-if="hasError">
    <strong>Error:</strong> <t t-esc="errorMessage"/>
</div>
```

### Diff Tint Colors (rgba with SCSS vars)

```scss
// app.scss — rgba() using SCSS variable functions
.ai-diff-cell {
    &.ai-diff-added   { background-color: rgba($o-success, 0.1); }
    &.ai-diff-removed { background-color: rgba($o-danger, 0.1); }
    &.ai-diff-changed { background-color: rgba($o-warning, 0.1); }
    &.ai-diff-unchanged { color: $o-gray-500; }
}
```

In dark mode, `$o-success/#1dc959` at 0.1 opacity on `#262A36` background creates a subtle green tint. Claude's discretion: may need to increase to `0.12`–`0.15` in dark if `#1dc959` at 10% doesn't read well.

### Flash Animation (rgba migration)

```scss
@keyframes ai-tree-flash {
    0%   { background-color: rgba($o-action, 0.3); }
    100% { background-color: transparent; }
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Catppuccin hardcoded hex | `$o-*` SCSS variables | Phase 9 | Single source compiles for both modes |
| Custom Notebook dark override | Enterprise `notebook.dark.scss` CSS variables | Pre-existing in enterprise | Delete our override block |
| `filter: invert(1)` on btn-close | Bootstrap 5's `$btn-close-color` dark override | Pre-existing in enterprise | Delete our dialog override block |
| Custom rgba error banner | Bootstrap `.alert-danger` component | Phase 9 | Requires XML change, not just SCSS |
| Selected row: `border-left: 3px solid accent` | `background-color: $o-component-active-bg` | Phase 9 | Matches Odoo list view pattern |

---

## Open Questions

1. **Diff tint opacity in dark mode**
   - What we know: `rgba($o-success, 0.1)` is the starting point; dark `$o-success = #1dc959`
   - What's unclear: Whether 10% opacity on dark backgrounds reads adequately without browser testing
   - Recommendation: Start at `0.1`, plan for a verification step to bump to `0.12`–`0.15` if needed (Claude's discretion)

2. **Light mode syntax colors**
   - What we know: Claude's discretion per CONTEXT.md; `$o-action` (#017e84) for keys, `$o-success` (#28a745) for strings work in light
   - What's unclear: Whether light mode `$o-warning` (#ffac00) for numbers is readable on white
   - Recommendation: Use `$o-gray-700` (#374151) for numbers in light or a muted `$o-action` variant; define light baseline in `app.scss` and override only in `app.dark.scss`

3. **Manifest: should `('remove', '**/*.dark.scss')` come before or after the glob?**
   - What we know: Odoo asset directives are order-dependent; `remove` applies to previously added files
   - What's unclear: Whether `('remove', ...)` before the glob works as a pre-filter
   - Recommendation: Follow web_gantt pattern exactly — add glob FIRST, then `('remove', '**/*.dark.scss')` after. This removes files already matched by the glob.

   **Corrected manifest pattern:**
   ```python
   'ai_debug.assets': [
       ('include', 'web.assets_backend'),
       'ai_debug/static/src/app/**/*.scss',   # adds all scss including dark
       ('remove', 'ai_debug/static/src/app/**/*.dark.scss'),  # then removes dark
       'ai_debug/static/src/app/**/*.xml',
       'ai_debug/static/src/app/**/*.js',
   ],
   ```

---

## Sources

### Primary (HIGH confidence)

- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/static/src/scss/primary_variables.dark.scss` — dark `$o-gray-*` values, dark semantic colors, dark `$o-main-code-color`
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/static/src/scss/primary_variables.scss` — enterprise light gray values and semantic colors
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/scss/primary_variables.scss` — base web gray scale and semantic color definitions
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/scss/secondary_variables.scss` — `$o-webclient-background-color` light definition
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/__manifest__.py` — `web.dark_mode_variables` bundle definition; dark.scss pattern
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_gantt/__manifest__.py` — `('remove', '**/*.dark.scss')` + re-add pattern
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/static/src/core/notebook/notebook.dark.scss` — confirms enterprise handles Notebook dark natively
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/static/src/scss/bootstrap_overridden.dark.scss` — dark modal/dropdown/input overrides; confirms modal bg auto-adapts through `$o-view-background-color`
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/scss/bootstrap_overridden.scss` — `$modal-content-bg: $o-view-background-color` in light mode

---

## Metadata

**Confidence breakdown:**
- Color mapping (Catppuccin → Odoo vars): HIGH — extracted directly from source SCSS files
- Dark variable values: HIGH — read directly from `primary_variables.dark.scss`
- Manifest ordering pattern: HIGH — confirmed in web_gantt and web_enterprise manifests
- Notebook/Dialog safe-to-delete: HIGH — enterprise dark SCSS files confirm native handling
- Diff tint opacity: MEDIUM — logical extrapolation; needs browser verification
- Light mode syntax colors: MEDIUM — Claude's discretion; aesthetics cannot be verified without rendering

**Research date:** 2026-02-22
**Valid until:** 2026-04-22 (stable SCSS variable system; unlikely to change)
