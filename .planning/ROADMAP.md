# Roadmap: AI Debugger

## Milestones

- ✅ **v1.0 AI Debugger MVP** — Phases 1-3 (shipped 2026-02-20)
- ✅ **v1.1 Live Tracer Standalone App** — Phases 4-7 (shipped 2026-02-22)
- **v1.2 Native Theming** — Phases 8-9 (in progress)

## Phases

<details>
<summary>✅ v1.0 AI Debugger MVP (Phases 1-3) — SHIPPED 2026-02-20</summary>

- [x] Phase 1: Data Models and Instrumentation (2/2 plans) — completed 2026-02-20
- [x] Phase 2: Backend Views (1/1 plan) — completed 2026-02-20
- [x] Phase 3: Live Panel and Polish (2/2 plans) — completed 2026-02-20

Full details: `.planning/milestones/v1.0-ROADMAP.md`

</details>

<details>
<summary>✅ v1.1 Live Tracer Standalone App (Phases 4-7) — SHIPPED 2026-02-22</summary>

- [x] Phase 4: Infrastructure (2/2 plans) — completed 2026-02-21
- [x] Phase 5: Bus Instrumentation (1/1 plan) — completed 2026-02-21
- [x] Phase 6: Sidebar Tree (5/5 plans) — completed 2026-02-21
- [x] Phase 7: Detail Panel (2/2 plans) — completed 2026-02-21

Full details: `.planning/milestones/v1.1-ROADMAP.md`

</details>

### v1.2 Native Theming

- [ ] **Phase 8: Theme Infrastructure** - Wire controller, template, and manifest to load CSS bundles conditionally based on color_scheme cookie
- [ ] **Phase 9: SCSS Migration and Dark Accents** - Replace all hardcoded colors in app.scss with SCSS variables and create dark-only accent overrides

## Phase Details

### Phase 8: Theme Infrastructure
**Goal**: The app correctly selects and loads its CSS bundle based on the user's Odoo theme preference
**Depends on**: Nothing (first phase of v1.2)
**Requirements**: INFRA-01, INFRA-02, INFRA-03
**Success Criteria** (what must be TRUE):
  1. Opening `/ai-debug` with the `color_scheme=dark` cookie results in DevTools Network showing two CSS requests: a JS-only load from `ai_debug.assets` and a CSS-only load from `ai_debug.assets_dark`
  2. Opening `/ai-debug` with the `color_scheme=light` cookie results in DevTools Network showing one CSS request from `ai_debug.assets` and no request for `ai_debug.assets_dark`
  3. The `ai_debug.assets_dark` bundle includes `web.dark_mode_variables` before `ai_debug.assets` — not `web.assets_backend` — so Odoo backend CSS is not double-compiled
  4. The rendered HTML source contains `color_scheme` in the template context (visible via page source inspection), confirming `webclient_rendering_context()` is called in the controller
**Plans:** 1 plan
Plans:
- [ ] 08-01-PLAN.md — Wire controller, manifest, and template for theme-aware CSS loading

### Phase 9: SCSS Migration and Dark Accents
**Goal**: The app is visually consistent with the Odoo theme in both light and dark modes, with zero hardcoded Catppuccin colors remaining
**Depends on**: Phase 8
**Requirements**: SCSS-01, SCSS-02, SCSS-03, SCSS-04, SCSS-05, COMP-01, COMP-02, DARK-01, DARK-02
**Success Criteria** (what must be TRUE):
  1. `grep -n "#[0-9a-fA-F]\{3,6\}\|rgba\|rgb(" app.scss` returns zero results — no hardcoded hex or RGBA values remain
  2. In light mode, the app renders with a light background consistent with Odoo's standard light theme; Notebook tabs and TextPopupDialog modal display without dark backgrounds or an inverted close button
  3. In dark mode, the app renders with a dark background consistent with Odoo's dark palette; JSON syntax highlighting is legible and status dots (running, done, error, paused) are visually distinct
  4. StateDiff tints (add/remove row highlights) are visible but not overpowering in both light and dark modes
  5. The connection status dot uses `$o-success` (connected) and `$o-danger` (disconnected) — semantic Odoo colors, not Catppuccin-specific values
**Plans**: TBD

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Data Models and Instrumentation | v1.0 | 2/2 | Complete | 2026-02-20 |
| 2. Backend Views | v1.0 | 1/1 | Complete | 2026-02-20 |
| 3. Live Panel and Polish | v1.0 | 2/2 | Complete | 2026-02-20 |
| 4. Infrastructure | v1.1 | 2/2 | Complete | 2026-02-21 |
| 5. Bus Instrumentation | v1.1 | 1/1 | Complete | 2026-02-21 |
| 6. Sidebar Tree | v1.1 | 5/5 | Complete | 2026-02-21 |
| 7. Detail Panel | v1.1 | 2/2 | Complete | 2026-02-21 |
| 8. Theme Infrastructure | v1.2 | 0/1 | Planning | - |
| 9. SCSS Migration and Dark Accents | v1.2 | 0/? | Not started | - |
