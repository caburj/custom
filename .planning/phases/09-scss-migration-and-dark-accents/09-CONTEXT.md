# Phase 9: SCSS Migration and Dark Accents - Context

**Gathered:** 2026-02-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Migrate all hardcoded Catppuccin hex/rgba colors in `app.scss` to Odoo SCSS variables (`$o-gray-*`, `$o-success`, `$o-danger`, etc.), remove unnecessary component override blocks (Notebook, Dialog), and create `app.dark.scss` for dark-mode-specific accent colors. The app must look visually consistent with Odoo's standard theme in both light and dark modes, with zero hardcoded colors remaining.

</domain>

<decisions>
## Implementation Decisions

### Light mode appearance
- Blend fully with Odoo's standard light UI — no custom "dev tool" identity in light mode
- All panels (sidebar, header, detail) use the same light background; borders alone define separation (no subtle depth differences between panels)
- Tree row selection should follow Odoo's standard list view selection style, not the current 3px left-border accent
- Code block backgrounds (JSON viewer, text previews, diff snapshots): Claude's discretion based on readability

### Dark syntax palette
- Match Odoo's own code editor / ace editor color scheme for dark mode syntax highlighting (JSON keys, strings, numbers, booleans)
- Light mode syntax colors: Claude's discretion — pick what reads best on the light background
- Null/undefined visual treatment: Claude's discretion
- Interactive element hover/active colors (JSON toggles, truncation links): Claude's discretion

### Status & diff colors
- Status mapping: Running = `$o-action`, Paused = `$o-warning`, Done = `$o-success`, Error = `$o-danger`
- Connection dot: Connected = `$o-success`, Disconnected = `$o-danger`
- Tree row status icons: Same semantic mapping — checkmark = `$o-success`, X = `$o-danger`, pause = `$o-warning`
- Diff tint opacity: Claude's discretion — adjust per mode for best readability
- Error/warning banners: Use Odoo's standard Bootstrap alert component styling (`.alert-danger`, etc.) instead of custom tinted backgrounds

### Component cleanup
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

</decisions>

<specifics>
## Specific Ideas

- Match Odoo's ace editor colors for dark syntax highlighting — look at what Odoo uses in its own code editor components
- Error banners should use standard Odoo/Bootstrap `.alert-danger` rather than custom rgba tinting
- Selection highlighting should match Odoo list view conventions — research how `.o_list_view` highlights selected rows

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 09-scss-migration-and-dark-accents*
*Context gathered: 2026-02-22*
