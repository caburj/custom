# Phase 8: Theme Infrastructure - Context

**Gathered:** 2026-02-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire the controller, template, and manifest so the app correctly selects and loads its CSS bundle based on the user's Odoo theme preference (`color_scheme` cookie). This phase delivers the infrastructure only — actual dark mode styling is Phase 9.

</domain>

<decisions>
## Implementation Decisions

### No-cookie fallback
- Missing `color_scheme` cookie is treated the same as `color_scheme=light` — no dark bundle loaded
- No explicit fallback logic needed; the template simply doesn't render the dark `t-call-assets` when the value isn't "dark"
- Theme updates on next page load — if user changes theme in Odoo Preferences, the AI Debugger tab picks up the new cookie on refresh (no live switching)
- No console logging of resolved theme — the template context already contains `color_scheme` (success criteria #4), which is sufficient for debugging

### Dev/test workflow
- Manual verification only — no automated Python tests for this infrastructure phase
- Verification can use either cookie manipulation in DevTools or Odoo Preferences toggle, whichever is practical
- Plan should include step-by-step manual verification instructions (DevTools Network tab, page source inspection) aligned with the success criteria
- Research and reference how Odoo's own web module (`webclient` template) handles dark mode CSS loading, and mirror that pattern

### Claude's Discretion
- Dark bundle contents for Phase 8 (whether to include a stub dark SCSS or just `web.dark_mode_variables`)
- Template conditional loading approach (t-call-assets with t-if vs other QWeb patterns)
- Controller implementation details for integrating `webclient_rendering_context()`

</decisions>

<specifics>
## Specific Ideas

- Mirror Odoo's own dark mode loading pattern from the web module — don't invent a new approach
- Success criteria are very specific about network request behavior (separate CSS-only load for dark bundle, JS-only load from main bundle)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 08-theme-infrastructure*
*Context gathered: 2026-02-22*
