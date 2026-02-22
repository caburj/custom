# Project Research Summary

**Project:** AI Debugger v1.2 — Native Theming
**Domain:** Odoo standalone OWL app — CSS theming migration
**Researched:** 2026-02-22
**Confidence:** HIGH

## Executive Summary

AI Debugger v1.2 migrates the standalone `/ai-debug` app from hardcoded Catppuccin Mocha colors to Odoo's native Bootstrap CSS variable theming system. This is a well-understood pattern in the Odoo codebase: both the main webclient and the POS standalone app use identical mechanisms. The approach is server-side bundle selection — the Python controller reads the `color_scheme` cookie at request time and conditionally loads either `ai_debug.assets` (light) or `ai_debug.assets_dark` (dark). No JavaScript theme switching, no media queries, no new dependencies. Every pattern required exists in the Odoo source and can be copied directly.

The recommended implementation has two distinct phases. Phase 1 is infrastructure: add `color_scheme` to the controller context (via `webclient_rendering_context()`), split the QWeb template into a JS-only base load plus a conditional CSS-only load, and define the `ai_debug.assets_dark` bundle in `__manifest__.py` using `('include', 'web.dark_mode_variables')` before `('include', 'ai_debug.assets')`. Phase 2 is the CSS migration itself: replace all hardcoded Catppuccin hex and RGBA values in `app.scss` with `$o-gray-*` SCSS variables and Bootstrap theme colors. A new `app.dark.scss` file handles any residual values (JSON syntax highlighting, status dots) that cannot be expressed as a single SCSS variable. The SCSS approach is compile-time — the same `app.scss` source produces different compiled output depending on which bundle it is compiled into, because `web.dark_mode_variables` injects dark variable overrides before compilation.

The primary risk is incomplete color replacement. The existing `app.scss` has approximately 40 distinct hardcoded hex values plus additional `rgba()` calls that a hex-only grep will miss. The app also has Notebook and Dialog color overrides that now conflict with the enterprise components' own `notebook.dark.scss` and Bootstrap's `--bs-modal-*` variables — those overrides must be removed rather than migrated. Testing only in dark mode (which approximates the current Catppuccin look) will hide light-mode regressions. Both modes must be verified after every change.

## Key Findings

### Recommended Stack

No new dependencies are required. All infrastructure is already present in the Odoo enterprise source. The migration uses three technologies: (1) `webclient_rendering_context()` on `ir.http` for server-side cookie resolution, (2) the `web.dark_mode_variables` asset bundle (defined by `web_enterprise`) for dark SCSS variable injection, and (3) `$o-gray-*` SCSS variables plus Bootstrap theme color variables (`$o-action`, `$o-danger`, etc.) for the color mappings.

**Core technologies:**
- `ir.http.webclient_rendering_context()`: server-side color scheme resolution — encapsulates cookie + user preference + default fallback in one call; base `ir.http` returns `'light'`, enterprise override adds full resolution logic
- `web.dark_mode_variables` asset bundle: dark SCSS variable injection — prepends `$o-gray-*` dark overrides before light variable files, causing the entire bundle SCSS compilation to use dark values; defined by `web_enterprise/__manifest__.py`
- `$o-gray-100` through `$o-gray-900` SCSS variables: compile-time color tokens — inverted scale in dark mode (gray-100 is darkest at `#1B1D26`, gray-900 is lightest at `#E4E4E4`); available in any SCSS file compiled within the asset bundle
- Bootstrap CSS custom properties (`--bs-body-bg`, `--bs-body-color`, `--bs-border-color`, etc.): runtime color tokens baked in at Sass compile time — values differ between light and dark bundles because the underlying SCSS variables differ; note Odoo strips the `bs-` prefix (Bootstrap CSS vars are unprefixed in Odoo, so `--body-bg` not `--bs-body-bg`)
- `color_scheme` cookie: set by `web_enterprise/controllers/home.py` on every `/web` response; values are `'light'` or `'dark'`; `'system'` is resolved server-side and never passed as-is to the template

**Important caveat:** `$enable-dark-mode: false` in Odoo's `bootstrap_overridden.scss` disables Bootstrap 5's built-in `[data-bs-theme="dark"]` block. Bootstrap's `--secondary-bg`, `--tertiary-bg`, `--secondary-color`, `--tertiary-color` CSS custom properties may not be emitted at `:root`. Use SCSS variables (`$o-gray-*`) rather than these secondary/tertiary Bootstrap CSS vars; SCSS variables are safe and verified in both bundles.

### Expected Features

**Must have (table stakes):**
- App respects user's Odoo theme preference — dark for dark users, light for light users. Currently the app is permanently dark regardless of user preference, which is visually jarring for light-mode users.
- Correct Bootstrap CSS custom properties in both modes — Bootstrap components (Notebook, Dialog) already in the app must have their SCSS variables set correctly by the loaded bundle, or they look wrong independently of app custom styles.
- All hardcoded Catppuccin values replaced with SCSS variables — approximately 40 hex values plus several `rgba()` calls across 650 lines of `app.scss`.

**Should have (polish):**
- Semantic Odoo colors for status indicators — replace Catppuccin green/red/yellow accent colors with `$o-success`, `$o-danger`, `$o-warning` so status dots and diff grid tints are consistent with the Odoo design system across both modes.
- System preference support — works automatically via `color_scheme_service.js` (already in `web.assets_backend`) once the controller passes `color_scheme` correctly.
- No flash of wrong-theme content — correct-by-default when bundle selection is server-side; no special blocking code needed.

**Defer (v2+):**
- Real-time in-app theme switch without page reload — Odoo's theming is compile-time (two separate bundles); runtime switching would require shipping both bundles or duplicating all variables as runtime CSS custom properties. Not how Odoo's own webclient works; not worth the complexity for a developer tool.
- In-app theme toggle button — users are internal developers with Odoo Preferences access; a second toggle duplicates the existing system and creates cookie sync problems.

**Anti-features (do not build):**
- `@media (prefers-color-scheme: dark)` CSS queries — Odoo's theme is user-controlled via cookie, not OS preference; using media queries creates a conflict between Odoo preference and OS preference.
- Separate `.dark.scss` files per component (mirroring web_enterprise's pattern) — web_enterprise uses this pattern because it has hundreds of components to override. This app has one SCSS file. Using `$o-gray-*` variables in a single `app.scss` is simpler and requires zero duplication.

### Architecture Approach

The architecture is a targeted modification of three existing files plus addition of one new file. The controller gains one line (`webclient_rendering_context()` replaces `session_info()`). The QWeb template gains a JS/CSS split and a `t-if="color_scheme == 'dark'"` conditional. The manifest gains one new bundle definition (`ai_debug.assets_dark`). The existing `app.scss` is modified in-place to replace hardcoded colors with SCSS variables. A new `app.dark.scss` covers any residual values that require dark-specific treatment (primarily JSON syntax highlight colors and custom RGBA tints). No JS files change. No Python models change. No bus protocol changes.

**Modified files:**
1. `controllers/main.py` — call `webclient_rendering_context()`, pass result to render context
2. `views/ai_debug_index.xml` — split `t-call-assets` into JS-only base + CSS-only conditional
3. `__manifest__.py` — add `ai_debug.assets_dark` bundle; add `('remove', '**/*.dark.scss')` to base bundle
4. `static/src/app/app.scss` — replace all hardcoded hex and rgba() colors with `$o-gray-*` and theme variables

**New file:**
5. `static/src/app/app.dark.scss` — dark-only overrides for values not expressible via a single SCSS variable (JSON syntax colors, status dot colors, flash animation rgba tint)

**Build order dependency:** The manifest bundle definition (step 3) must be done alongside the template change (step 2) — the template references `ai_debug.assets_dark` which must exist before the template renders. Steps 1-3 should be committed together as infrastructure. Steps 4-5 (CSS migration) are iterative and independent once infrastructure is in place.

### Critical Pitfalls

1. **Controller missing `color_scheme`** — calling `session_info()` instead of `webclient_rendering_context()` means `color_scheme` is undefined in the template, the `t-if` conditional evaluates false, and the dark bundle never loads. This is the #1 pitfall — if it is wrong, the entire feature appears broken with no CSS error to indicate the cause. Fix: replace `session_info()` with `webclient_rendering_context()`.

2. **Incomplete RGBA replacement** — hex-only grep (`grep "#[0-9a-f]{3,6}"`) misses the `rgba()` calls in `app.scss` that also contain hardcoded Catppuccin RGB triples. These look approximately correct in dark mode (similar palette) but render wrong in light mode. Run a second grep pass: `grep -n "rgba\|rgb(" app.scss`. Replace `rgba(137, 180, 250, 0.05)` with `rgba($o-action, 0.05)` etc.

3. **Dark bundle double-compiling Odoo CSS** — defining `ai_debug.assets_dark` to include `web.assets_backend` (instead of `ai_debug.assets`) causes the entire Odoo backend CSS to compile twice. Correct structure: `('include', 'web.dark_mode_variables')` followed by `('include', 'ai_debug.assets')`. The dark bundle replaces the base bundle for CSS; it does not load alongside it.

4. **Notebook and Dialog color overrides conflict with enterprise components** — `app.scss` has explicit color overrides for `.o_notebook .nav-tabs` (lines ~357-392) and `.o_dialog .modal-content` (lines ~618-638) including a `.btn-close { filter: invert(1) }` hack. These now conflict with `notebook.dark.scss` and Bootstrap's `--bs-modal-*` variables. Remove the color properties from these blocks entirely; keep only structural/layout rules.

5. **Testing only in dark mode hides light-mode regressions** — the existing Catppuccin dark values are close enough to the Odoo dark palette that partial replacements pass visual QA in dark mode. Light mode is the true test for this migration. Always verify both modes after any CSS change.

## Implications for Roadmap

The natural phase structure is infrastructure first, CSS migration second. These are independent tracks with one dependency at their seam: the infrastructure must be in place before the CSS migration can be verified end-to-end.

### Phase 1: Theme Infrastructure

**Rationale:** The controller, template, and manifest changes are a single logical unit — they must be consistent with each other or the page crashes (template references undefined bundle) or silently loads the wrong bundle (controller missing `color_scheme`). These three changes have no visual CSS impact yet; they can be verified by inspecting the rendered HTML source and the DevTools network tab. Doing infrastructure first isolates the "does the dark bundle load?" question from the "do the CSS variables look right?" question.

**Delivers:** A working conditional bundle-load mechanism. In dark mode, DevTools Network shows two CSS bundle requests (JS-only from `ai_debug.assets` via `t-css="false"`, and CSS from `ai_debug.assets_dark` via `t-js="false"`). In light mode, one CSS bundle loads. The app looks identical to today (still has hardcoded colors) but is now correctly wired to the theme system.

**Addresses:**
- Bundle selection from `color_scheme` cookie (P1 feature)
- Dark bundle definition in `__manifest__.py` (P1 feature)
- `web.dark_mode_variables` in dark bundle (P1 feature)

**Avoids:**
- Pitfall 1: Controller missing `color_scheme` (use `webclient_rendering_context()`)
- Pitfall 3: Dark bundle double-compiling Odoo CSS (use `ai_debug.assets` as base, not `web.assets_backend`)
- Pitfall 8: Real-time JS theme switching attempted

**Verification checklist:**
- `webclient_rendering_context()` called in controller; `color_scheme` in template context
- HTML source shows dark `<link>` tag only when `color_scheme=dark` cookie is set
- JS loaded once via `t-css="false"`; CSS loaded conditionally via `t-js="false"`
- No `web.assets_backend` in dark bundle definition (uses `('include', 'ai_debug.assets')` instead)
- `('remove', 'ai_debug/static/src/app/**/*.dark.scss')` in base bundle definition

### Phase 2: SCSS Variable Migration

**Rationale:** With infrastructure in place, the CSS migration is a systematic search-and-replace across one file (`app.scss`). The natural grouping is by semantic category: structural backgrounds first (easiest to verify visually), then text and borders, then accent and status colors, then the residual RGBA and syntax-highlighting values that go to `app.dark.scss`. Doing it category-by-category means each group of changes is verifiable in both light and dark mode before moving on. The Notebook and Dialog override removals come after the main variable pass so the overall light-mode baseline is established before the component-specific conflicts are resolved.

**Delivers:** An app that is visually consistent with the Odoo theme in both light and dark modes. After this phase, `grep -n "#[0-9a-fA-F]\{3,6\}\|rgba\|rgb(" app.scss` returns zero results. Light mode looks like a standard Odoo light-mode page. Dark mode matches the Odoo dark palette (not identical to Catppuccin, but coherent with the Odoo design system).

**Addresses:**
- SASS variable replacement in `app.scss` (P1 feature — the main implementation work)
- Semantic Odoo colors for status indicators (P2 feature)

**Avoids:**
- Pitfall 2: Hardcoded colors overriding Bootstrap variables
- Pitfall 4: Notebook and Dialog override conflicts (remove color-only rules from those blocks)
- Pitfall 5: Testing only in dark mode (explicit two-mode verification after each group)
- Pitfall 6: RGBA hardcoded colors missed by hex-only grep (run both grep passes)
- Pitfall 7: JsonTree and StateDiff SCSS classes not audited

**Sub-tasks within this phase (natural order):**
1. Structural backgrounds: `$o-view-background-color` for app bg, `$o-webclient-background-color` for sidebar/header, `$o-gray-300` for borders
2. Text colors: `$o-main-text-color` for primary, `$o-gray-500`/`$o-gray-400` for secondary/muted
3. Accent and status: `$o-action`, `$o-success`, `$o-danger`, `$o-warning`, `$o-info`
4. Remove Notebook and Dialog color overrides (a deletion, not a replacement)
5. RGBA audit: replace rgba() Catppuccin triples with `rgba($o-variable, opacity)`
6. `app.dark.scss`: JSON syntax highlight colors, status dot colors, flash animation tint

**Verification checklist (must pass in both light and dark mode):**
- No hardcoded hex or rgba() values remain in `app.scss`
- Notebook tabs themed correctly by enterprise's `notebook.dark.scss` (no app.scss color rules needed)
- TextPopupDialog modal renders correctly (no dark background in light mode, no inverted close button)
- JsonTree syntax colors legible against both backgrounds
- StateDiff tints visible but subtle in both modes
- Status dot uses `$o-success` (connected) and `$o-danger` (disconnected)
- Flash animation uses `rgba($o-action, 0.3)` not hardcoded Catppuccin blue

### Phase Ordering Rationale

The infrastructure/CSS split is forced by dependency: the template must reference a defined bundle. Within the CSS migration, the ordering (backgrounds → text → accent → cleanup → RGBA → dark-only) moves from the most visually obvious to the most subtle, ensuring each step's result is immediately verifiable. Deleting the Notebook and Dialog overrides is placed after general color replacement so that the overall light-mode appearance is established before the specific component conflicts are addressed — this avoids discovering that an override was masking a different problem.

### Research Flags

All patterns are fully documented from direct Odoo source inspection. Neither phase requires additional research before implementation.

**Standard patterns — no research-phase needed:**
- **Phase 1 (Infrastructure):** Exact pattern verified against `web/views/webclient_templates.xml` and `point_of_sale/views/pos_assets_index.xml`. Controller pattern verified against `web_enterprise/models/ir_http.py`. Bundle structure verified against `web_enterprise/__manifest__.py` and `pos_enterprise/__manifest__.py`.
- **Phase 2 (CSS Migration):** SCSS variable values verified against `primary_variables.dark.scss`. Color mappings verified by cross-referencing current `app.scss` colors with their semantic roles. Component conflicts (Notebook, Dialog) verified by inspecting `notebook.dark.scss` and `bootstrap_overridden.dark.scss`.

**One item to verify during implementation (not a blocker):** Bootstrap's `--secondary-bg`, `--tertiary-bg`, `--secondary-color`, `--tertiary-color` CSS custom properties may not be emitted at `:root` because `$enable-dark-mode: false` in Odoo. The safe path — using `$o-gray-*` SCSS variables instead of these CSS custom properties — is already the recommended approach and avoids this uncertainty entirely.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All patterns verified from direct source reads of Odoo master and enterprise at local worktree paths. No web search or LLM inference. `webclient_rendering_context()`, `web.dark_mode_variables`, and the `$o-gray-*` scale all confirmed at specific file paths and line numbers. |
| Features | HIGH | Feature landscape grounded in direct inspection of the current `app.scss` (existing state) and all relevant enterprise SCSS/JS files. MVP scope is narrow and unambiguous: 5 files, 2 phases, zero new dependencies. |
| Architecture | HIGH | Modified files identified precisely. Build order dependencies verified. The only structural decision (use `ai_debug.assets` as dark bundle base, not `web.assets_backend`) confirmed by inspecting `pos_enterprise/__manifest__.py`. |
| Pitfalls | HIGH | All 8 pitfalls grounded in actual observed code in the existing `app.scss` and controller — not hypothetical. Line numbers referenced for the Notebook (357-392) and Dialog (618-638) conflicts. Two-grep audit protocol specified for hex and rgba() values. |

**Overall confidence:** HIGH

### Gaps to Address

- **Bootstrap secondary/tertiary CSS custom property availability:** `$enable-dark-mode: false` may suppress some Bootstrap 5.3 `:root` variables. This is a potential issue only if anyone reaches for `var(--bs-secondary-bg)` in SCSS rather than `$o-gray-*`. Mitigate by defaulting to SCSS variables throughout Phase 2 and only using CSS custom properties where a runtime value is genuinely needed.

- **Exact count of RGBA values in `app.scss`:** Research identified the categories (diff grid tints, ancestor tint, flash animation) but did not enumerate all occurrences. The Phase 2 RGBA audit (`grep -n "rgba\|rgb(" app.scss`) will establish the complete list. Expected count is under 10 but must be verified rather than assumed.

- **Visual quality of Odoo semantic colors for JSON syntax highlighting:** Catppuccin uses a distinct 6-color syntax palette; Odoo's semantic palette has 5 colors with different hue/saturation characteristics. The mapping (strings → `$o-success`, numbers → `$o-warning`, booleans → `$o-info`, keys → `$o-action`, null → `$o-gray-400`) is semantically reasonable but the visual result has not been previewed. Acceptable for a developer tool; adjust in `app.dark.scss` if the light-mode result is poor.

## Sources

### Primary (HIGH confidence — direct source inspection at local worktree paths)

- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/models/ir_http.py` — `color_scheme()` method, `webclient_rendering_context()` method
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/controllers/home.py` — `color_scheme` cookie set on every webclient response
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/models/ir_http.py` — base `color_scheme()` returns `"light"`; `webclient_rendering_context()` bundles both fields
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/views/webclient_templates.xml` lines 311-319 — authoritative pattern: JS-only bundle + conditional CSS-only bundle
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/point_of_sale/views/pos_assets_index.xml` — standalone app cookie-conditional bundle pattern
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/__manifest__.py` — `web.dark_mode_variables`, `web.assets_web_dark`, `('remove', '**/*.dark.scss')` definitions
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/__manifest__.py` — `web.assets_backend` removes `*.dark.scss`; `web.assets_web_dark` structure
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/static/src/scss/primary_variables.dark.scss` — dark palette SCSS variable values (gray-100=`#1B1D26`, gray-900=`#E4E4E4`)
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/static/src/scss/primary_variables.scss` — light palette SCSS variable values
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/lib/bootstrap/scss/_root.scss` — Bootstrap CSS custom property declarations
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/scss/bootstrap_overridden.scss` — `$variable-prefix: ''` (no `bs-` prefix on CSS vars), `$enable-dark-mode: false`
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/static/src/core/notebook/notebook.dark.scss` — `--Notebook__link-background-color` CSS custom property pattern
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/pos_enterprise/__manifest__.py` — `point_of_sale.assets_prod_dark` using `('include', 'web.dark_mode_variables')` — confirms standalone dark bundle pattern
- `/Users/joseph/clones/odoo/custom/ai_debug/static/src/app/app.scss` — current module SCSS (650 lines, ~40 hardcoded hex values, rgba tints, Notebook + Dialog overrides at lines 357-392 and 618-638)
- `/Users/joseph/clones/odoo/custom/ai_debug/controllers/main.py` — current controller (calls `session_info()` only, missing `color_scheme`)
- `/Users/joseph/clones/odoo/custom/ai_debug/views/ai_debug_index.xml` — current template (no color_scheme conditional, loads only `ai_debug.assets`)

---
*Research completed: 2026-02-22*
*Ready for roadmap: yes*
