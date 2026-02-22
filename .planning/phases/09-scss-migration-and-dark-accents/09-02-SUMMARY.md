---
phase: 09-scss-migration-and-dark-accents
plan: 02
subsystem: frontend/theming
tags: [scss, dark-mode, bootstrap, asset-bundles]
dependency_graph:
  requires: []
  provides: [dark-syntax-highlighting, dark-bundle-config, bootstrap-error-banners]
  affects: [ai_debug.assets, ai_debug.assets_dark]
tech_stack:
  added: []
  patterns: [dark-scss-bundle-exclusion, bootstrap-alert-semantic]
key_files:
  created:
    - ai_debug/static/src/app/app.dark.scss
  modified:
    - ai_debug/__manifest__.py
    - ai_debug/static/src/app/detail/iter_detail.xml
    - ai_debug/static/src/app/detail/tc_detail.xml
decisions:
  - "Use $o-warning for .ai-json-number in dark mode (warm amber contrast) vs $o-gray-700 in light"
  - "Bootstrap alert-danger replaces custom ai-detail-error-banner for automatic dark-mode adaptation"
metrics:
  duration: 59s
  completed: 2026-02-22
  tasks_completed: 2
  tasks_planned: 2
  files_created: 1
  files_modified: 3
---

# Phase 9 Plan 02: Dark Bundle Config and Bootstrap Error Banners Summary

**One-liner:** Dark-specific SCSS file with `$o-*` syntax highlighting, excluded from light bundle via remove directive and compiled after `web.dark_mode_variables` in dark bundle; error banners migrated to Bootstrap `alert-danger`.

## What Was Built

### Task 1: app.dark.scss (commit c05d71d)

Created `ai_debug/static/src/app/app.dark.scss` with 5 syntax highlighting classes that override light-mode values when compiled in the dark bundle:

- `.ai-json-key` — `$o-action` (teal in dark vs blue in light, same var different resolved value)
- `.ai-json-string` — `$o-success` (green, auto-adapts)
- `.ai-json-number` — `$o-warning` (warm amber — key difference from light's `$o-gray-700`)
- `.ai-json-boolean` — `$o-main-code-color` (matches Odoo ace editor dark scheme)
- `.ai-json-null` — `$o-gray-500` + italic

Zero hardcoded hex colors. Color-only overrides, no layout or spacing.

### Task 2: Manifest + XML error banners (commit 2f5ff34)

**Manifest:** Added `('remove', 'ai_debug/static/src/app/**/*.dark.scss')` after the SCSS glob in `ai_debug.assets` (light bundle). Added `'ai_debug/static/src/app/**/*.dark.scss'` after `('include', 'web.dark_mode_variables')` in `ai_debug.assets_dark`, ensuring dark variables are injected before dark SCSS compiles.

**XML:** Replaced `class="ai-detail-error-banner"` with `class="alert alert-danger mb-0 rounded-0 border-start-0 border-end-0 py-2 px-3"` in both `iter_detail.xml` and `tc_detail.xml`. Changed `<span>Error:</span>` to `<strong>Error:</strong>` for semantics.

## Verification Results

- app.dark.scss exists: YES
- `$o-*` variable count: 8 (5 classes, some with 1 var each, font-style not counted)
- Hardcoded hex colors: 0
- `('remove', '**/*.dark.scss')` in manifest light bundle: YES
- `'**/*.dark.scss'` after `web.dark_mode_variables` in dark bundle: YES
- `ai-detail-error-banner` remaining in XML: 0 (class still exists in app.scss as dead CSS — deferred)
- Bootstrap `alert-danger` in iter_detail.xml: 1
- Bootstrap `alert-danger` in tc_detail.xml: 1

## Deviations from Plan

None — plan executed exactly as written.

**Observation (not a deviation):** The `.ai-detail-error-banner` CSS rule in `app.scss` (line 423) is now dead code since neither XML uses it. This is out of scope for this plan and deferred to Phase 9 Plan 01's SCSS cleanup work.

## Self-Check: PASSED

Files verified:
- FOUND: ai_debug/static/src/app/app.dark.scss
- FOUND: ai_debug/__manifest__.py (updated)
- FOUND: ai_debug/static/src/app/detail/iter_detail.xml (updated)
- FOUND: ai_debug/static/src/app/detail/tc_detail.xml (updated)

Commits verified:
- FOUND: c05d71d — feat(09-02): create app.dark.scss
- FOUND: 2f5ff34 — feat(09-02): configure dark bundle and migrate error banners
