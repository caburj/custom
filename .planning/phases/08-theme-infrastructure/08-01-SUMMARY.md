---
phase: 08-theme-infrastructure
plan: 01
subsystem: infra
tags: [odoo, qweb, dark-mode, assets, color-scheme, webclient]

# Dependency graph
requires: []
provides:
  - Controller exposes color_scheme via webclient_rendering_context() in QWeb render context
  - Manifest defines ai_debug.assets_dark bundle (web.dark_mode_variables + ai_debug.assets)
  - Template splits JS/CSS asset loading with color_scheme-conditional CSS bundle selection
affects:
  - 09-css-migration (Phase 9 adds dark SCSS overrides to ai_debug.assets_dark)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Split t-call-assets pattern: t-css=false for unconditional JS, t-js=false for conditional CSS (mirrors web.webclient_bootstrap)"
    - "webclient_rendering_context() in controller instead of session_info() directly"
    - "Dark bundle as include chain: web.dark_mode_variables + ai_debug.assets"

key-files:
  created: []
  modified:
    - ai_debug/controllers/main.py
    - ai_debug/__manifest__.py
    - ai_debug/views/ai_debug_index.xml

key-decisions:
  - "Use webclient_rendering_context() not raw cookie reading — handles user settings, public user guard, and future extension points"
  - "Dark bundle includes ai_debug.assets (not web.assets_backend) to avoid stripping dark variables"
  - "No explicit no-cookie fallback logic — t-else branch fires when color_scheme is falsy, loading light CSS"
  - "Version bumped to 1.2 to reflect the theming infrastructure addition"

patterns-established:
  - "Pattern: Standalone Odoo app dark mode — webclient_rendering_context() + split t-call-assets in template"

requirements-completed: [INFRA-01, INFRA-02, INFRA-03]

# Metrics
duration: 5min
completed: 2026-02-22
---

# Phase 8 Plan 01: Theme Infrastructure Summary

**Controller/manifest/template wired for Odoo native dark mode: webclient_rendering_context() exposes color_scheme, ai_debug.assets_dark bundle defined, template conditionally loads dark or light CSS bundle via split t-call-assets pattern**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-02-22T08:44:37Z
- **Completed:** 2026-02-22T08:49:00Z
- **Tasks:** 1 of 2 (Task 2 is a human-verify checkpoint)
- **Files modified:** 3

## Accomplishments
- Controller now calls `webclient_rendering_context()` instead of `session_info()` directly, making `color_scheme` available in the QWeb render context
- Manifest defines `ai_debug.assets_dark` bundle with `web.dark_mode_variables` + `ai_debug.assets` includes, positioned after the base bundle
- Template splits asset loading: JS loaded unconditionally via `t-css="false"`, CSS loaded conditionally — dark bundle when `color_scheme == 'dark'`, light bundle otherwise via `t-else`
- Version bumped from 1.1 to 1.2

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire controller, manifest, and template for theme-aware CSS loading** - `3789290` (feat)

**Plan metadata:** pending (docs commit after human-verify checkpoint)

## Files Created/Modified
- `ai_debug/controllers/main.py` - Replaced session_info() with webclient_rendering_context(), passes full context dict to template
- `ai_debug/__manifest__.py` - Added ai_debug.assets_dark bundle, bumped version to 1.2
- `ai_debug/views/ai_debug_index.xml` - Replaced single t-call-assets with split JS-only + conditional CSS-only pattern

## Decisions Made
- `webclient_rendering_context()` over direct cookie reading — the method handles user settings override, public user guard, and is the Odoo-standard approach used by web module itself
- Dark bundle uses `('include', 'ai_debug.assets')` not `('include', 'web.assets_backend')` — avoids re-including the light bundle that strips `*.dark.scss` files, which would undo dark variable injection
- No explicit no-cookie fallback logic needed — the `t-else` branch fires whenever `color_scheme` is not exactly `'dark'`, which covers missing/null/light cases

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Theme infrastructure wiring is complete and committed
- Phase 9 can add `ai_debug/static/src/app/app.dark.scss` and prepend it to `ai_debug.assets_dark` in the manifest
- Awaiting human verification (Task 2 checkpoint): DevTools Network tab tests for dark/light cookie switching

---
*Phase: 08-theme-infrastructure*
*Completed: 2026-02-22*
