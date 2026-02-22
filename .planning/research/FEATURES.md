# Feature Research

**Domain:** Native Odoo theming in standalone OWL app (ai_debug v1.2)
**Researched:** 2026-02-22
**Confidence:** HIGH — all findings verified by direct source code review of Odoo master branch (enterprise + core)

---

## Context: What Already Exists vs What This Milestone Adds

**v1.1 (shipped):** All colors hardcoded as Catppuccin Mocha values in `app.scss` (~97 hardcoded hex/rgba values in one file). App is permanently dark regardless of user preference.

**v1.2 goal:** App respects the user's Odoo theme preference (light or dark) by reading the `color_scheme` cookie at server render time and loading the appropriate asset bundle.

---

## How Odoo Theming Actually Works (Source-Verified)

### The `color_scheme` Cookie System

Odoo Enterprise's theming infrastructure is cookie-driven with three components:

**1. Server-side cookie (Python):** `web_enterprise/controllers/home.py` sets a `color_scheme` cookie on every `/web` response. The value is resolved by `ir.http.color_scheme()` which checks (in priority order): the user's `res.users.settings.color_scheme` field (`system` | `light` | `dark`), then falls back to `"light"`. When `system` is selected, the server returns `"light"` (it cannot detect `prefers-color-scheme` server-side).

**2. Client-side reconciliation (JS):** `color_scheme_service.js` (web_enterprise) runs at startup. It compares the cookie to `window.matchMedia('(prefers-color-scheme:dark)').matches`. If they disagree, it updates the cookie and does `location.reload()`. This is what makes `system` preference actually work for Odoo's main backend.

**3. Template-side bundle switching (XML):** The webclient template checks `color_scheme == 'dark'` and conditionally loads `web.assets_web_dark` (CSS-only) instead of `web.assets_web` (CSS-only, loaded separately from JS).

### How the POS Standalone App Does It

The POS index template (`point_of_sale/views/pos_assets_index.xml`) checks `request.cookies.get('pos_color_scheme') == 'dark'` and loads either `point_of_sale.assets_prod_dark` or `point_of_sale.assets_prod`. The POS uses its own separate cookie (`pos_color_scheme`) because it's a different auth context (public kiosk). The dark toggle is added by `pos_enterprise` via a navbar button that sets the cookie and reloads.

### What `web.assets_web_dark` Contains

From `web/__manifest__.py`:
```python
"web.assets_web_dark": [
    ('include', 'web.assets_web'),  # includes all light mode CSS + JS
    'web/static/src/**/*.dark.scss', # adds dark overrides on top
],
```

From `web_enterprise/__manifest__.py`, it also adds:
- `web.dark_mode_variables` (dark SASS variable overrides for `$o-gray-*`, `$o-webclient-background-color`, etc.)
- `web_enterprise/static/src/**/*.dark.scss` (component-specific dark overrides)

### How `ai_debug.assets` Currently Works

The current bundle is:
```python
'ai_debug.assets': [
    ('include', 'web.assets_backend'),  # includes all light mode CSS + JS
    'ai_debug/static/src/app/**/*.scss',  # app.scss with hardcoded Catppuccin Mocha
    'ai_debug/static/src/app/**/*.xml',
    'ai_debug/static/src/app/**/*.js',
],
```

`web.assets_backend` already excludes `*.dark.scss` files (`('remove', 'web/static/src/**/*.dark.scss')`). This means the current bundle is always light-mode Bootstrap + dark Catppuccin Mocha custom CSS — a contradictory mix.

### The `color_scheme` Cookie Is Already Set

When any internal user loads `/web` in Odoo Enterprise before navigating to `/ai-debug`, the `color_scheme` cookie is already set by `web_enterprise`'s home controller. The cookie value is `"light"` or `"dark"`. The ai_debug controller can read it immediately at `request.httprequest.cookies.get('color_scheme')`.

---

## Feature Landscape

### Table Stakes (Users Expect These)

These are the features that make the theming "complete" from the user's perspective. Missing them makes the UI feel broken or inconsistent.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **App respects user's Odoo theme preference** — dark for dark users, light for light users | User sets "Dark" in Odoo Preferences. Every other Odoo page is dark. The ai_debug standalone app is jarring if it ignores the preference. | LOW | Read `color_scheme` cookie in the controller. Conditionally load dark vs light asset bundle. No new user-facing settings needed. |
| **Correct Bootstrap CSS custom properties** — `$body-bg`, `$body-color`, `$border-color`, `$dropdown-bg` match the active theme | The app uses Bootstrap classes on Odoo OWL components (Notebook, Dialog). If the Bootstrap SASS variables are not from the dark variant, Bootstrap components look visually wrong even if custom CSS is correct. | LOW | Solved by including `web.dark_mode_variables` in the dark bundle, which re-declares `$o-gray-*` and `$o-webclient-background-color` before Bootstrap compiles them. |
| **Custom app colors respond to theme switch** — hardcoded Catppuccin Mocha values replaced | Currently 97 hardcoded hex/rgba values. In light mode these make the app look dark regardless of user preference. In dark mode they should also be replaced with SASS variables from Odoo's dark palette. | MEDIUM | All hardcoded values in `app.scss` replaced with `$o-gray-*`, `$o-action`, `$o-danger`, etc. This is the main implementation work. |
| **Page reload when theme changes in Odoo** — switching theme in Odoo Preferences takes effect on next visit | Odoo's `color_scheme_service.js` reloads the main backend when the cookie changes. The ai_debug app (in a separate tab) gets the correct theme on next page load. No real-time theme switching is needed within the tab itself. | LOW | Correct-by-default. The bundle is selected at server render time from the cookie. Odoo's existing reload mechanism handles the main backend. |

### Differentiators (Optional Polish — Not Blocking)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Monochrome palette** — replace Catppuccin accent colors (blue, green, red, yellow) with Odoo's semantic colors (`$o-action`, `$o-danger`, `$o-success`, `$o-warning`) | The current Catppuccin palette has arbitrary accent colors. Using Odoo's semantic variables means status colors (error = `$o-danger`, running = `$o-action`) are consistent with what the developer sees elsewhere in Odoo. | LOW | A subset of the color replacement work. Replace `#f38ba8` (Catppuccin red) with `$o-danger`, `#a6e3a1` with `$o-success`, `#89b4fa` with `$o-action`, `#f9e2af` with `$o-warning`. |
| **`system` preference support** — app detects OS-level dark mode when user has chosen "System" | Odoo's main backend supports this via `color_scheme_service.js` reconciling the cookie with `prefers-color-scheme`. The ai_debug app gets this for free if `color_scheme_service.js` is included in the bundle (it is, via `web.assets_backend`). | LOW | Requires the controller to pass `color_scheme` to the template. The service then reconciles at client startup. Cookie is already set to the correct value by `web_enterprise`'s home controller when user visits `/web` first. |
| **Smooth first-paint** — no flash of unstyled/wrong-theme content | Odoo's main webclient avoids theme flicker by blocking render until `color_scheme_service` has reconciled the cookie. The ai_debug app can achieve this simply by always loading the cookie-appropriate bundle at server render time (no client-side reconciliation needed for first paint). | LOW | Correct-by-default if bundle selection happens server-side in the controller. No special blocking needed since the app isn't going to "switch theme on the fly". |

### Anti-Features (Do Not Build)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **In-app theme toggle button** — a sun/moon button in the ai_debug header | "I want to switch themes without going back to Odoo Preferences." | The ai_debug app is a developer tool, not a consumer product. A theme toggle duplicates Odoo's existing preference system (Preferences → Theme). The POS does this (`pos_enterprise` adds a navbar button and its own `pos_color_scheme` cookie) because POS is used by cashiers who may not have access to Odoo backend settings. ai_debug users are always internal Odoo developers who already have Preferences access. Maintaining a second cookie creates sync problems. | Direct users to Odoo Preferences for theme changes. |
| **CSS custom properties at runtime** — switching theme without page reload via JS-toggled CSS variables | "Real-time theme switching is smoother." | Odoo's entire theming system is compile-time (SASS variables compiled into two separate CSS bundles). Implementing runtime switching would require either duplicating all variable declarations as CSS custom properties, or shipping both bundles and toggling stylesheets — neither of which Odoo's own main backend does. | Match Odoo's behavior: bundle selected at server render time, page reload required to change theme. |
| **Custom color palette user preference** — "I want to use a different theme color" | "The Odoo dark theme is purple. I prefer a blue theme." | Out of scope for a developer tool. Odoo does not expose theme color customization to internal users (only website themes support this). The ai_debug app should be minimal and consistent with the Odoo design system. | Use `$o-enterprise-color` and `$o-action` as-is. No color customization. |
| **Separate dark SCSS files (`app.dark.scss`)** — mirroring web_enterprise's component-by-component pattern | "That's the Odoo pattern for dark mode." | The web_enterprise pattern (one `.dark.scss` per component) exists because web_enterprise must override thousands of light-mode values across hundreds of components. The ai_debug app has one SCSS file with ~97 color values. Splitting into `app.scss` + `app.dark.scss` creates two files to maintain when one file using `$o-gray-*` variables covers both modes with zero duplication. | Replace hardcoded values with SASS variables. One file, no duplication. The dark bundle's `web.dark_mode_variables` re-declares those variables before compilation, so the same `app.scss` compiles to different values depending on which bundle is built. |

---

## Feature Dependencies

```
[Dark bundle selection — server side]
    └──requires──> [color_scheme cookie readable in controller]
    └──requires──> [New dark asset bundle defined in __manifest__.py]
    └──enables──> [Correct Bootstrap variables in dark mode]

[SASS variable replacement in app.scss]
    └──requires──> [Dark bundle selection] (variables only produce correct output if compiled with dark_mode_variables)
    └──replaces──> [Hardcoded Catppuccin Mocha values]
    └──uses──> [$o-gray-100 through $o-gray-900, $o-action, $o-danger, $o-success, $o-warning]

[web.dark_mode_variables in dark bundle]
    └──requires──> [web_enterprise installed] (web.dark_mode_variables is defined by web_enterprise)
    └──enables──> [$o-gray-* variables compile to dark values instead of light values]

[color_scheme cookie set correctly]
    └──provided-by──> [web_enterprise home controller] (already happens when user visits /web)
    └──no-action-needed-in──> [ai_debug controller for internal users who have visited /web]
```

### Dependency Notes

- **`web.dark_mode_variables` is defined by `web_enterprise`, not core `web`.** This means the dark bundle depends on `web_enterprise` being installed. Since ai_debug requires `ai_app` which is enterprise-only, `web_enterprise` is always present. This dependency is implicit but safe.
- **The `color_scheme` cookie is set by the main backend, not the ai_debug route.** A user who opens `/ai-debug` directly without visiting `/web` first may not have the cookie set. In that case `request.cookies.get('color_scheme')` returns `None`, and the controller should default to `'light'`. The client-side `color_scheme_service.js` (included via `web.assets_backend`) then reconciles the cookie at startup on subsequent loads.
- **SASS variable replacement is compile-time, not runtime.** Two separate bundles are compiled: one using light SASS variables, one using dark SASS variables. The same `app.scss` source produces different CSS depending on which bundle it's compiled into. This is the correct Odoo pattern.
- **`$o-gray-*` scale is inverted in dark mode.** In light mode `$o-gray-100` is near-white, `$o-gray-900` is near-black. In dark mode (from `primary_variables.dark.scss`) these values are swapped: `$o-gray-100: #1B1D26` (dark), `$o-gray-900: #E4E4E4` (near-white). Code using `$o-gray-100` as a "light background" will correctly produce dark backgrounds in dark mode without any special casing.

---

## MVP Definition

### Launch With (v1.2)

The minimum that makes the app theme-aware. A developer with dark mode enabled sees a dark app. A developer with light mode sees a light app.

- [ ] **Define `ai_debug.assets_dark` bundle** in `__manifest__.py` — includes `web.dark_mode_variables`, `('before', ...)` for bootstrap overrides, all `web_enterprise` dark SCSS, and `ai_debug/static/src/app/**/*.scss`
- [ ] **Controller passes `color_scheme` to template** — read `request.httprequest.cookies.get('color_scheme', 'light')` and pass to Qweb render context
- [ ] **Template conditionally loads dark bundle** — `t-if="color_scheme == 'dark'"` loads `ai_debug.assets_dark`, otherwise loads `ai_debug.assets`
- [ ] **Replace 97 hardcoded values in `app.scss` with SASS variables** — `$o-gray-*` for surfaces/text/borders, `$o-action` for accent/selection, `$o-danger`/`$o-success`/`$o-warning` for status colors

### Add After Validation (v1.2.x)

- [ ] **System preference support verification** — test that `color_scheme_service.js` correctly reconciles OS-level dark mode preference when user has set "System" in Odoo Preferences

### Future Consideration (v2+)

- [ ] **Real-time theme switch within tab** — only if user research shows developers switch themes frequently enough to warrant the complexity

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Bundle selection from `color_scheme` cookie | HIGH | LOW | P1 — the enabling mechanism |
| Dark bundle definition in `__manifest__.py` | HIGH | LOW | P1 — required for dark CSS compilation |
| SASS variable replacement in `app.scss` | HIGH | MEDIUM | P1 — the main implementation work |
| `web.dark_mode_variables` in dark bundle | HIGH | LOW | P1 — required for correct dark SASS output |
| System preference reconciliation | MEDIUM | LOW | P2 — works via existing `color_scheme_service.js` |
| In-app theme toggle | LOW | MEDIUM | ANTI-FEATURE — do not build |
| Runtime CSS variable switching | LOW | HIGH | ANTI-FEATURE — do not build |

---

## Reference App Analysis

How Odoo standalone apps handle theming (source-verified):

| App | Cookie | Bundle Strategy | User Toggle | Notes |
|-----|--------|-----------------|-------------|-------|
| Odoo Backend (`/web`) | `color_scheme` | Conditionally loads `web.assets_web_dark` (CSS-only) | Via Preferences → Theme field | `color_scheme_service.js` reconciles cookie with `prefers-color-scheme` at startup |
| POS (`/pos/ui`) | `pos_color_scheme` | Conditionally loads `point_of_sale.assets_prod_dark` | Via navbar burger menu (pos_enterprise) | Separate cookie because POS users may not be internal Odoo users; toggle added by pos_enterprise |
| Self-Order (`/pos-self/`) | None | No dark mode support | N/A | Public-facing kiosk; no theming |
| **ai_debug** (v1.2 target) | `color_scheme` (existing, set by backend) | Conditionally loads `ai_debug.assets_dark` | Via Odoo Preferences (no in-app toggle) | Internal developer tool; reuses the same cookie as the main backend |

**Key insight:** ai_debug should use the same `color_scheme` cookie as the main backend — not a separate cookie like POS. This is correct because ai_debug users are always internal users who have already visited `/web` (where the cookie is set). Using the same cookie means the theme preference is automatically in sync with the user's Odoo preference with zero additional infrastructure.

---

## Sources

- `web_enterprise/controllers/home.py` — `color_scheme` cookie set on `/web` response (HIGH confidence — direct source)
- `web_enterprise/models/ir_http.py` — `color_scheme()` method resolving user setting vs cookie (HIGH confidence — direct source)
- `web_enterprise/models/res_users_settings.py` — `color_scheme` field definition: `['system', 'light', 'dark']` (HIGH confidence — direct source)
- `web_enterprise/static/src/webclient/color_scheme/color_scheme_service.js` — client-side reconciliation of cookie vs OS preference (HIGH confidence — direct source)
- `web_enterprise/__manifest__.py` — `web.dark_mode_variables` and `web.assets_web_dark` bundle definitions (HIGH confidence — direct source)
- `web_enterprise/static/src/scss/primary_variables.dark.scss` — dark mode SASS variable values (`$o-gray-*` inverted scale) (HIGH confidence — direct source)
- `web/__manifest__.py` — `web.assets_backend` removes `*.dark.scss`, `web.assets_web_dark` includes all `*.dark.scss` (HIGH confidence — direct source)
- `web/views/webclient_templates.xml` — `color_scheme == 'dark'` conditional bundle loading pattern (HIGH confidence — direct source)
- `point_of_sale/views/pos_assets_index.xml` — `pos_color_scheme` cookie pattern for standalone app (HIGH confidence — direct source)
- `pos_enterprise/__manifest__.py` — `point_of_sale.assets_prod_dark` bundle definition with dark variables (HIGH confidence — direct source)
- `pos_enterprise/static/src/override/point_of_sale/navbar/navbar.js` — in-app toggle writing `pos_color_scheme` cookie (HIGH confidence — direct source)
- `ai_debug/__manifest__.py` and `ai_debug/static/src/app/app.scss` — current state of the module (HIGH confidence — direct source)

---

*Feature research for: Native Odoo theming in standalone OWL app (ai_debug v1.2)*
*Researched: 2026-02-22*
