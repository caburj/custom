---
phase: 09-scss-migration-and-dark-accents
plan: 01
subsystem: ui
tags: [scss, theming, dark-mode, odoo-variables, catppuccin]

requires:
  - phase: 08-theme-infrastructure
    provides: "Dark bundle wiring (ai_debug.assets_dark), webclient_rendering_context(), dark CSS variables available at compile time"

provides:
  - "app.scss fully migrated to Odoo SCSS variables — zero hardcoded hex or rgba values"
  - "Dead component override blocks removed (Notebook colors, Dialog, CopyButton, error banner)"
  - "Selected row uses $o-component-active-bg (Odoo list view pattern), no border-left accent"
  - "Status dots/icons use $o-success/$o-danger/$o-warning semantic variables"
  - "JSON syntax colors set as light-mode baseline using Odoo semantic variables"
  - "Minimal layout-only Notebook block preserved (flex fill for detail view)"
  - "Minimal font-only popup content block preserved (no colors)"

affects: [09-02, 09-03, app.dark.scss creation]

tech-stack:
  added: []
  patterns:
    - "All panel backgrounds use $o-webclient-background-color (sidebar, header, app shell) or $o-view-background-color (detail content area only)"
    - "All borders use $border-color ($o-gray-300) for primary or $o-gray-200 for subtle section dividers"
    - "rgba() values use SCSS variable arguments: rgba($o-action, 0.3) not rgba(137, 180, 250, 0.3)"
    - "Dead override blocks stripped entirely — trust Odoo enterprise SCSS for Notebook/Dialog dark mode"
    - "Error banner class deleted from SCSS; XML migration to .alert-danger handled in Plan 02"

key-files:
  created: []
  modified:
    - ai_debug/static/src/app/app.scss

key-decisions:
  - "All panels use same $o-webclient-background-color background — borders define separation (no depth differences per locked decision)"
  - "Selected row: $o-component-active-bg only, no border-left accent (Odoo list view pattern per locked decision)"
  - "JSON numbers use $o-gray-700 in light mode (not $o-warning which is too bright on white)"
  - "Notebook block: keep flex layout properties only, strip all color overrides"
  - "Popup content: keep font/whitespace properties only, strip all color/background/padding"
  - "Error banner SCSS class deleted; XML migration to Bootstrap .alert-danger deferred to Plan 02"

patterns-established:
  - "Variable-only color replacement: same app.scss source compiles correctly for both light and dark bundles"
  - "rgba($o-variable, opacity) pattern for semi-transparent tints (diff cells, flash animation, ancestor highlight)"

requirements-completed: [SCSS-01, SCSS-02, SCSS-03, SCSS-04, SCSS-05, COMP-01, COMP-02, DARK-02]

duration: 2min
completed: 2026-02-22
---

# Phase 9 Plan 01: SCSS Migration Summary

**All 231 hardcoded Catppuccin hex/rgba values in app.scss replaced with 66 Odoo $o-* variable references; five dead component override blocks removed (Notebook colors, Dialog, CopyButton, error banner, popup colors)**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-22T09:42:06Z
- **Completed:** 2026-02-22T09:44:25Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Zero hardcoded colors remain in app.scss — same source file now compiles correctly for both light and dark CSS bundles without runtime JavaScript
- Five dead override blocks removed: Notebook (colors only, layout kept), Dialog (full block including filter:invert hack), CopyButton, error banner, popup content colors
- Selected row selection migrated from 3px left-border accent to $o-component-active-bg background tint (Odoo list view pattern per locked decision)
- Status semantics unified: connected=$o-success, disconnected=$o-danger, tree icons=$o-success/$o-danger/$o-warning
- JSON syntax colors set as light-mode baseline: keys=$o-action, strings=$o-success, numbers=$o-gray-700, booleans=$o-main-code-color, null=$o-gray-500 italic

## Task Commits

Both tasks operated on the same file and were completed in a single atomic write:

1. **Task 1: Replace all hardcoded hex and rgba colors** - `17f5792` (refactor)
2. **Task 2: Remove dead component override blocks** - `17f5792` (refactor, same commit)

**Plan metadata:** (forthcoming — docs commit)

## Files Created/Modified

- `ai_debug/static/src/app/app.scss` - Full color migration: 0 hex colors, 0 raw rgba(), 66 $o-* usages, 9 $border-color usages. Dead blocks removed. Net: -155 lines (76 added, 155 deleted)

## Decisions Made

- JSON numbers use $o-gray-700 in light mode, not $o-warning (#ffac00 is too bright on white background)
- All panels use $o-webclient-background-color — borders define visual separation, not background depth differences
- Popup content retains only font/whitespace properties (no color, no background, no padding)
- Notebook retains only flex layout properties (no color overrides at all)
- Error banner SCSS class deleted; XML migration to Bootstrap .alert-danger is Plan 02 scope

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- app.scss is fully variable-driven; ready for Plan 02 (XML error banner migration to .alert-danger, any remaining template changes)
- app.dark.scss creation (Plan 02 or 03) will override JSON syntax colors for dark mode using same $o-* variables
- Manifest changes for *.dark.scss exclusion/ordering already researched in 09-RESEARCH.md Pattern 3

---
*Phase: 09-scss-migration-and-dark-accents*
*Completed: 2026-02-22*
