# Architecture Research

**Domain:** Odoo standalone OWL app — AI agentic loop live tracer (v1.1 → v1.2 theming)
**Researched:** 2026-02-22 (theming section added; v1.1 base retained)
**Confidence:** HIGH (grounded in actual source at verified paths)

---

# v1.2 Theming Architecture

> This section answers the research questions for v1.2 milestone: How does native theming integrate with a standalone OWL app? How is `color_scheme` detected? How does the template serve the correct CSS bundle? How should SCSS be restructured?

## How Odoo's Theming System Works

Odoo's theme system has three layers. Understanding all three is required to integrate correctly.

### Layer 1: User preference storage (enterprise only)

`web_enterprise/models/res_users_settings.py` adds a `color_scheme` field (`Selection: light/dark/system`). `res.users` exposes this as `color_scheme` (via `related`). The preference persists across sessions.

### Layer 2: Server-side color_scheme resolution

`web_enterprise/models/ir_http.py` overrides `color_scheme()`:

```python
def color_scheme(self):
    cookie_scheme = request.httprequest.cookies.get('color_scheme')
    scheme = cookie_scheme if cookie_scheme else super().color_scheme()
    if user := request.env.user:
        if user._is_public():
            return super().color_scheme()           # light for public
        if user_scheme := user.res_users_settings_id.color_scheme:
            if user_scheme in ('light', 'dark'):    # not 'system'
                return user_scheme                  # user explicit choice wins
    return scheme                                   # cookie fallback
```

The base `web/models/ir_http.py` returns `"light"` as the hardcoded default. The enterprise override reads the cookie first, then the user's explicit setting if it's not `'system'`. **'system' is not passed through** — the server cannot know the OS preference, so `color_scheme()` never returns `'system'`, only `'light'` or `'dark'`.

### Layer 3: Cookie synchronization

`web_enterprise/controllers/home.py` sets the cookie on every webclient visit:

```python
@route()
def web_client(self, s_action=None, **kw):
    response = super().web_client(s_action, **kw)
    if response.status_code == 200:
        response.set_cookie('color_scheme', request.env['ir.http'].color_scheme())
    return response
```

This means: every time the user visits `/odoo`, Odoo sets (or refreshes) the `color_scheme` cookie to `'light'` or `'dark'`. **The ai_debug controller can read this cookie directly** to determine which CSS bundle to serve.

## Data Flow: Theme Detection to CSS Bundle

```
User sets theme in Odoo Settings
    ↓
res.users_settings.color_scheme = 'dark'
    ↓
User visits /odoo → web_enterprise.home.web_client()
    → request.env['ir.http'].color_scheme()
        → reads user.res_users_settings_id.color_scheme → 'dark'
    → response.set_cookie('color_scheme', 'dark')
    ↓
Cookie 'color_scheme' = 'dark' persists in browser
    ↓
User navigates to /ai-debug
    ↓
AiDebugController.ai_debug()
    → request.httprequest.cookies.get('color_scheme')  # 'dark'
    → pass to QWeb template context: color_scheme='dark'
    ↓
ai_debug.index QWeb template
    → <t t-if="color_scheme == 'dark'">
    →     <t t-call-assets="ai_debug.assets_dark" .../>
    → <t t-else="">
    →     <t t-call-assets="ai_debug.assets" .../>
    ↓
Browser loads either ai_debug.assets (light) or ai_debug.assets_dark (dark)
    ↓
Bootstrap CSS variables resolve to light or dark values
    ↓
App renders with Odoo-native color palette
```

**Confidence: HIGH** — verified directly from `web_enterprise/models/ir_http.py`, `web_enterprise/controllers/home.py`, and `web/views/webclient_templates.xml` (`web.webclient_bootstrap` template shows the exact pattern).

## The Exact Webclient Bootstrap Pattern (Reference)

`web/views/webclient_templates.xml` (`web.webclient_bootstrap`) is the authoritative reference:

```xml
<t t-call-assets="web.assets_web_print" media="print" t-js="false"/>
<t t-call-assets="web.assets_web" t-css="false"/>   <!-- always: JS only -->

<t t-if="color_scheme == 'dark'">
    <t t-call-assets="web.assets_web_dark" media="screen" t-js="false"/>
</t>
<t t-else="">
    <t t-call-assets="web.assets_web" media="screen" t-js="false"/>
</t>
```

Key observations:
1. JS is loaded once from `web.assets_web` (CSS-free pass, `t-css="false"`).
2. CSS is loaded separately from either the light bundle or the dark bundle.
3. `web.assets_web_dark` includes everything in `web.assets_web` PLUS dark SCSS files.
4. The `media="screen"` attribute is added to the CSS link tag to allow a print bundle to coexist.

The ai_debug template should follow this same split: one JS-only bundle, one CSS-only conditional.

## How `web.assets_web_dark` Works

`web/__manifest__.py`:
```python
"web.assets_web_dark": [
    ('include', 'web.assets_web'),        # everything in light mode
    'web/static/src/**/*.dark.scss',      # plus all *.dark.scss files
],
```

`web_enterprise/__manifest__.py` extends it:
```python
"web.assets_web_dark": [
    ('include', 'web.dark_mode_variables'),     # dark SCSS variable overrides
    # web._assets_backend_helpers overrides:
    ('before', 'web_enterprise/static/src/scss/bootstrap_overridden.scss',
               'web_enterprise/static/src/scss/bootstrap_overridden.dark.scss'),
    ('after', 'web/static/lib/bootstrap/scss/_functions.scss',
              'web_enterprise/static/src/scss/bs_functions_overridden.dark.scss'),
    # assets_backend dark files:
    'web_enterprise/static/src/**/*.dark.scss',
],
```

The `web.dark_mode_variables` sub-bundle prepends dark SCSS variable overrides before the light-mode variable files. This means Sass compiles with dark values, so all compiled CSS already uses the dark palette. The `.dark.scss` files then add component-specific overrides that can't be handled by variables alone.

**Critical insight:** The dark mode is NOT CSS `prefers-color-scheme` media query. It is a **server-selected separate CSS bundle**. The server decides which bundle to serve based on the user's stored preference. There is no runtime CSS switching.

## How Bootstrap CSS Variables Are Emitted

Bootstrap 5 emits CSS custom properties on `:root` from `_root.scss`:

```css
:root, [data-bs-theme="light"] {
  --bs-body-color: #{$body-color};
  --bs-body-bg: #{$body-bg};
  --bs-border-color: #{$border-color};
  --bs-secondary-bg: #{$body-secondary-bg};
  --bs-tertiary-bg: #{$body-tertiary-bg};
  /* ...many more... */
}
```

The SCSS variables (`$body-color`, `$body-bg`, etc.) are resolved at Sass compile time. In the dark bundle, Odoo's dark variable overrides are prepended, so Bootstrap's `$body-bg` compiles to a dark value like `#1B1D26`. The resulting `--bs-body-bg` CSS custom property in the dark bundle's output is already the dark color — it was baked in at build time, not switched at runtime.

**What this means for ai_debug:** By using `var(--bs-body-bg)` instead of hardcoded `#1e1e2e`, the SCSS will pick up whichever value the loaded bundle compiled in.

## Available Bootstrap CSS Custom Properties

These are available from the `web.assets_backend` (and `ai_debug.assets`) bundle and change value between light and dark bundles:

| CSS Custom Property | Light value (approx) | Dark value (approx) | Use for |
|---------------------|----------------------|----------------------|---------|
| `--bs-body-bg` | `#ffffff` | `#1B1D26` (gray-100) | Page/panel backgrounds |
| `--bs-body-color` | `#212529` | `#E4E4E4` (gray-900) | Primary text |
| `--bs-secondary-bg` | `#f8f9fa` | `#262A36` (gray-200) | Sidebar, header backgrounds |
| `--bs-tertiary-bg` | `#e9ecef` | `#3C3E4B` (gray-300) | Hover states |
| `--bs-border-color` | `#dee2e6` | varies | Dividers, borders |
| `--bs-secondary-color` | `#6c757d` | `#7E8392` (gray-600) | Muted text |
| `--bs-emphasis-color` | `#000` | `#E4E4E4` | Strong emphasis text |
| `--bs-primary` | `#017e84` | adjusted | Accent/action color |
| `--bs-success` | `#198754` | `#1dc959` | Success indicators |
| `--bs-danger` | `#dc3545` | `#ff5757` | Error indicators |
| `--bs-warning` | `#ffc107` | `#FBB56A` | Warning indicators |

**Confidence: HIGH** — verified from `_root.scss`, `primary_variables.dark.scss`, and `bootstrap_overridden.dark.scss`.

Note: The grays (`$o-gray-100` through `$o-gray-900`) are inverted in dark mode: gray-100 is the darkest (background), gray-900 is the lightest (text). Bootstrap CSS custom properties like `--bs-secondary-bg` map to these.

## Odoo-Specific CSS Custom Properties

Odoo defines additional `--o-*` CSS custom properties. These are sparse and not comprehensively emitted. For theming, prefer Bootstrap's `--bs-*` properties which are well-defined and consistently emitted in both bundles.

## How the POS Handles It (Comparison)

POS (`point_of_sale/views/pos_assets_index.xml`) uses a POS-specific cookie:

```xml
<t t-if="request.cookies.get('pos_color_scheme') == 'dark'">
    <t t-call-assets="point_of_sale.assets_prod_dark"/>
</t>
<t t-else="">
    <t t-call-assets="point_of_sale.assets_prod"/>
</t>
```

POS reads a `pos_color_scheme` cookie (separate from `color_scheme`). ai_debug should read the main `color_scheme` cookie directly since it serves internal Odoo users who have already set their preference via the standard Odoo settings.

## Architecture for v1.2

### Modified Files

**`controllers/main.py`** (modified — add `color_scheme` to template context):

```python
from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.utils import is_user_internal


class AiDebugController(http.Controller):

    @http.route('/ai-debug', type='http', auth='user', readonly=True)
    def ai_debug(self, **kw):
        if not is_user_internal(request.session.uid):
            return request.redirect('/web/login', 303)
        session_info = request.env['ir.http'].session_info()
        color_scheme = request.httprequest.cookies.get('color_scheme', 'light')
        return request.render('ai_debug.index', {
            'session_info': session_info,
            'color_scheme': color_scheme,
        })
```

**`views/ai_debug_index.xml`** (modified — conditional CSS bundle, JS-only base):

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <template id="index" name="AI Debug">&lt;!DOCTYPE html&gt;
        <html>
            <head>
                <title>AI Debugger</title>
                <meta charset="utf-8"/>
                <meta http-equiv="X-UA-Compatible" content="IE=edge"/>
                <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no"/>
                <script type="text/javascript">
                    var odoo = {
                        csrf_token: "<t t-out="request.csrf_token(None)"/>",
                        debug: "<t t-out="debug"/>",
                        __session_info__: <t t-out="json.dumps(session_info)"/>,
                    };
                </script>
                <!-- JS only (no CSS) — same for both themes -->
                <t t-call-assets="ai_debug.assets" t-css="false"/>
                <!-- CSS only — conditional on color_scheme cookie -->
                <t t-if="color_scheme == 'dark'">
                    <t t-call-assets="ai_debug.assets_dark" t-js="false"/>
                </t>
                <t t-else="">
                    <t t-call-assets="ai_debug.assets" t-js="false"/>
                </t>
            </head>
            <body/>
        </html>
    </template>
</odoo>
```

**`__manifest__.py`** (modified — add `ai_debug.assets_dark` bundle):

```python
'assets': {
    'ai_debug.assets': [
        ('include', 'web.assets_backend'),
        'ai_debug/static/src/app/**/*.xml',
        'ai_debug/static/src/app/**/*.js',
        # SCSS that works in light mode (no hardcoded dark colors)
        'ai_debug/static/src/app/**/*.scss',
        # Exclude dark-mode-only files from the base bundle
        ('remove', 'ai_debug/static/src/app/**/*.dark.scss'),
    ],
    'ai_debug.assets_dark': [
        ('include', 'ai_debug.assets'),
        # Dark mode variable overrides (reuse enterprise's dark variables)
        ('include', 'web.dark_mode_variables'),
        # Component-specific dark overrides
        'ai_debug/static/src/app/**/*.dark.scss',
    ],
    'web.assets_backend': [
        'ai_debug/static/src/debug_menu_button.js',
    ],
},
```

**`static/src/app/app.scss`** (modified — replace hardcoded colors with CSS vars):

The existing `app.scss` has ~650 lines of hardcoded Catppuccin Mocha colors. These are replaced with Bootstrap CSS custom properties. The file stays as `app.scss` (light-mode baseline). A new `app.dark.scss` handles any colors that can't be expressed via `--bs-*` vars alone.

**`static/src/app/app.dark.scss`** (new — dark-only overrides for remaining values):

This file is only included in `ai_debug.assets_dark`. It handles the few cases where the dark theme needs values that differ from what `--bs-*` provides (e.g., custom Catppuccin accent colors for JSON syntax highlighting, status dots, badge colors).

### SCSS Restructuring Strategy

The restructuring maps each hardcoded Catppuccin Mocha color to the semantically closest Bootstrap CSS custom property:

| Current hardcoded value | Semantic meaning | Replacement |
|-------------------------|-----------------|-------------|
| `#1e1e2e` (base) | Page background | `var(--bs-body-bg)` |
| `#181825` (mantle) | Header/darker surface | `var(--bs-secondary-bg)` |
| `#11111b` (crust) | Detail panel darkest | `var(--bs-body-bg)` or `color-mix(in srgb, var(--bs-body-bg) 80%, black)` |
| `#313244` (surface1) | Borders, dividers | `var(--bs-border-color)` |
| `#45475a` (surface2) | Subtle borders | `color-mix(in srgb, var(--bs-border-color) 70%, var(--bs-body-bg))` |
| `#585b70` (overlay0) | Disabled/muted text | `var(--bs-secondary-color)` |
| `#6c7086` (overlay1) | Section labels | `var(--bs-secondary-color)` |
| `#a6adc8` (subtext1) | Secondary text | `var(--bs-secondary-color)` |
| `#cdd6f4` (text) | Primary text | `var(--bs-body-color)` |
| `#89b4fa` (blue) | Selected/accent | `var(--bs-primary)` |
| `#a6e3a1` (green) | Success | `var(--bs-success)` |
| `#f38ba8` (red) | Error/danger | `var(--bs-danger)` |
| `#f9e2af` (yellow) | Warning | `var(--bs-warning)` |
| `#fab387` (peach) | Numbers (JSON) | `var(--bs-warning)` |
| `#cba6f7` (mauve) | Booleans (JSON) | `var(--bs-primary)` or keep in `app.dark.scss` |
| `#2a2a3e` (hover) | Tree row hover | `var(--bs-tertiary-bg)` |
| `#2d3748` (selected bg) | Tree row selected | `color-mix(in srgb, var(--bs-primary) 15%, var(--bs-body-bg))` |
| `rgba(137,180,250,.05)` (ancestor) | Ancestor tint | `color-mix(in srgb, var(--bs-primary) 5%, transparent)` |

Colors that cannot be expressed with a single CSS variable (syntax highlighting colors like JSON key blue, JSON string green) belong in `app.dark.scss` as dark-specific overrides.

**Light mode baseline:** When `ai_debug.assets` (not dark) is loaded, the Bootstrap CSS variables resolve to light values. `app.scss` using `var(--bs-body-bg)` will naturally get a white/light background. The app will look like a standard Odoo light-mode page, which is the correct behavior.

### New vs Modified Files Summary

| File | Status | What changes |
|------|--------|--------------|
| `controllers/main.py` | **Modified** | Add `color_scheme` cookie read, pass to template context |
| `views/ai_debug_index.xml` | **Modified** | Split `t-call-assets` into JS-only + CSS conditional |
| `__manifest__.py` | **Modified** | Add `ai_debug.assets_dark` bundle definition; update `ai_debug.assets` to exclude `*.dark.scss` |
| `static/src/app/app.scss` | **Modified** | Replace all hardcoded hex colors with `var(--bs-*)` properties |
| `static/src/app/app.dark.scss` | **New** | Dark-only overrides for values not expressible via BS vars (JSON syntax colors, status dot colors) |

No JS files change. No Python models change. No bus protocol changes.

### Build Order for v1.2

Dependencies determine this order:

1. **`controllers/main.py`** — read the `color_scheme` cookie, add to render context. Verifiable immediately: hit `/ai-debug`, check QWeb rendering context in debug mode.

2. **`views/ai_debug_index.xml`** — split `t-call-assets` into JS-only + conditional CSS. Verifiable: with dark cookie set, check browser DevTools network tab for which CSS file loads.

3. **`__manifest__.py`** — add `ai_debug.assets_dark` bundle. Must be done before step 2 is useful, otherwise `ai_debug.assets_dark` is undefined and the template crashes. **Do steps 2 and 3 together.**

4. **`static/src/app/app.scss`** — replace hardcoded colors with CSS custom properties. Do this color category by category: backgrounds first (body, header, sidebar), then borders, then text, then accent/status colors. Verify in both light and dark mode after each group.

5. **`static/src/app/app.dark.scss`** — add overrides for any remaining values that the light-mode `var(--bs-*)` substitutions don't handle correctly in dark mode (e.g., JSON syntax highlighting colors, status dot colors that need Catppuccin-specific accents).

**Step 3 must precede step 2** (bundle must exist before template references it). Steps 4 and 5 are independent of steps 1-3 and can be done iteratively after the infrastructure is in place.

---

# v1.1 Base Architecture (Unchanged)

> The following is the v1.1 architecture document, retained for reference.

## What Changed in v1.1

v1.0 used: persistent DB models + backend XML views + OWL client action panel.
v1.1 replaces that with: no DB models + standalone OWL app at `/ai-debug` + full bus payloads.

This document focuses on the v1.1 target architecture. v1.0 patterns that carry over unchanged (generator yield passthrough, separate cursor bus sends) are referenced but not re-explained in full.

---

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                     INSTRUMENTATION LAYER (unchanged)                │
│                                                                      │
│  AiSessionDebug (_inherit = 'ai.session')                            │
│  ├── _run_agentic_loop()   — wraps super(), captures events          │
│  ├── _handle_tool_calls()  — wraps super(), captures tool events     │
│  └── _generate_next_response() — captures instructions + RAG        │
│           │                                                          │
│           │  No DB writes. Sends via separate cursor:                │
│           ▼                                                          │
├──────────────────────────────────────────────────────────────────────┤
│                  REAL-TIME NOTIFICATION LAYER                        │
│                                                                      │
│  bus.bus._sendone('ai_debug:traces', event_type, FULL_PAYLOAD)       │
│                                                                      │
│  Events (all carry full data — no lazy DB reads):                    │
│  ├── ai_debug/new_trace    — loop start, instructions, tools def     │
│  ├── ai_debug/iteration    — messages_sent, raw_response, timing     │
│  ├── ai_debug/tool_call    — args, result, state_before/after        │
│  └── ai_debug/trace_update — state, termination_reason              │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│                       HTTP LAYER (new in v1.1)                       │
│                                                                      │
│  AiDebugController                                                   │
│  └── GET /ai-debug  →  renders 'ai_debug.index' template            │
│                         (auth='user', internal users only)           │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│                   STANDALONE OWL APP LAYER (new)                     │
│                                                                      │
│  ai_debug.index (QWeb template — full HTML page, no Odoo chrome)     │
│  └── loads asset bundle: ai_debug.assets                            │
│      └── main.js → mountComponent(AiDebugApp, document.body)        │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │  AiDebugApp  (root OWL component)                           │     │
│  │  ├── TraceList  (sidebar — loops, with agent label)         │     │
│  │  │   ├── LoopItem (clickable, shows status badge)          │     │
│  │  │   │   ├── IterationItem (LLM call, duration)           │     │
│  │  │   │   │   └── ToolCallItem (tool name, success badge)  │     │
│  │  │   │   └── ...                                          │     │
│  │  │   └── ...                                              │     │
│  │  └── DetailPanel  (right pane — context for selection)     │     │
│  │      ├── LoopDetail  (system prompt, tools definition)     │     │
│  │      ├── IterationDetail  (messages sent, raw response)    │     │
│  │      └── ToolCallDetail  (args, result, state diff)        │     │
│  └─────────────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Implementation |
|-----------|----------------|----------------|
| `AiSessionDebug` | Generator yield passthrough; emits full bus payloads | `TransientModel`, `_inherit = 'ai.session'`, unchanged from v1.0 except payload content |
| `ir.websocket` (inherit) | Restricts `ai_debug:*` channels to `group_system` users | `AbstractModel`, `_build_bus_channel_list` override — carried over from v1.0 |
| `AiDebugController` | Serves the standalone app HTML page at `/ai-debug` | `http.Controller`, `auth='user'`, renders `ai_debug.index` QWeb template |
| `ai_debug.index` (template) | Full HTML page: CSRF token, `__session_info__`, asset bundle | QWeb template declared in views XML; bootstraps OWL app |
| `ai_debug.assets` (bundle) | JS + CSS for the standalone app | Declared in `__manifest__.py`; includes OWL, web core services, bus service |
| `main.js` | Boots the OWL app | `mountComponent(AiDebugApp, document.body)` from `@web/env` |
| `AiDebugApp` | Root component; owns bus subscription and all trace state | OWL `Component`; `useState` for traces map; `useService('bus_service')` |
| `TraceList` | Sidebar tree: loop > iteration > tool call | Receives traces from parent; emits selection events upward |
| `DetailPanel` | Right pane; renders context for selected item | Receives `selection` prop (type + data); switches between sub-components |
| `JsonTree` | Collapsible JSON tree renderer | Pure presentational; carries over from v1.0 |
| `StateDiff` | Before/after state comparison | Pure presentational; carries over from v1.0 |

---

## Recommended Project Structure (v1.1 actual + v1.2 additions)

```
ai_debug/
├── __manifest__.py                   # v1.2: add assets_dark bundle
├── __init__.py
├── controllers/
│   ├── __init__.py
│   └── main.py                       # v1.2: add color_scheme cookie read
├── models/
│   ├── __init__.py
│   ├── ai_session.py                 # unchanged: generator instrumentation
│   └── ir_websocket.py               # unchanged: channel access control
├── views/
│   └── ai_debug_index.xml            # v1.2: conditional CSS bundle
└── static/src/
    ├── debug_menu_button.js
    └── app/
        ├── main.js
        ├── app.js
        ├── app.xml
        ├── app.scss                   # v1.2: replace hex colors with var(--bs-*)
        ├── app.dark.scss              # v1.2: NEW — dark-only overrides
        └── detail/
            ├── iter_detail.js/xml
            ├── json_tree.js/xml
            ├── loop_detail.js/xml
            ├── state_diff.js/xml
            ├── tc_detail.js/xml
            └── text_popup.js/xml
```

---

## Architectural Patterns

### Pattern 1: Standalone OWL App — Controller + Template + Asset Bundle

This is the POS Self Order pattern, which is simpler than full POS and has no session management complexity.

**What:** A dedicated HTTP route renders a full HTML page (no Odoo chrome/navbar). The template inlines the CSRF token and `__session_info__` as a JS global, then loads a custom asset bundle. The bundle's `main.js` boots an OWL app via `mountComponent`.

**When to use:** Any tool that should live in its own browser tab, free of the Odoo backend navbar.

`mountComponent` from `@web/env` calls `makeEnv()` + `startServices(env)` internally, which initializes the Odoo service registry (including `bus_service`, `orm`, `rpc`, `notification`). All services registered in `web.assets_backend` service registry are available.

### Pattern 2: Full Bus Payloads — No Lazy ORM Reads

**What:** The bus payloads carry complete data. There are no DB models, so all data must travel in the bus payload at event time.

**When to use:** Always, when there is no DB to fall back to.

**Trade-offs:** Payloads can be large. `messages_sent` for a multi-turn conversation can be tens of KB. The `bus_bus` table stores each payload as JSONB — no size constraint from pg_notify (that limit applies to the channel list notification, not the message payload).

### Pattern 3: OWL App State Management — Reactive Store in Root Component

**What:** The root component `AiDebugApp` owns the entire application state as `useState` objects. Child components receive state slices as props. Uses `useState(new Map())` for the trace store (not `reactive()` without callback, which uses NO_CALLBACK sentinel and blocks OWL render).

**When to use:** Apps with a bounded set of entity types and simple selection state.

### Pattern 4: Conditional CSS Bundle — Server-Side Theme Selection

**What:** The controller reads the `color_scheme` cookie set by the standard Odoo webclient. The QWeb template conditionally loads `ai_debug.assets_dark` vs `ai_debug.assets` for the CSS. JS is always loaded from `ai_debug.assets` (t-css="false").

**When to use:** Any standalone Odoo app that should respect user theme preference.

**Trade-offs:** Theme is determined at page load. If the user changes their Odoo theme in another tab, they must reload `/ai-debug` to pick it up. This matches the behavior of the main Odoo webclient.

---

## Data Flow

### Theme Selection Flow

```
User visits /odoo → Odoo sets color_scheme cookie ('light' or 'dark')
    ↓
User navigates to /ai-debug
    ↓
AiDebugController reads cookie → passes color_scheme to QWeb context
    ↓
QWeb template: t-if="color_scheme == 'dark'" → loads assets_dark CSS
    ↓
Bootstrap CSS vars resolve to dark values (compiled into bundle at build time)
    ↓
app.scss's var(--bs-body-bg) etc. get dark colors automatically
```

### Capture Flow (Python — write path)

```
HTTP call triggers agentic loop
    ↓
AiSessionDebug._run_agentic_loop()
    ├── Generate trace_id = uuid.uuid4()
    ├── _debug_bus_send_full('new_trace', {full trace payload})
    ├── for each LLM yield:
    │   ├── Generate iteration_id = uuid.uuid4()
    │   ├── _debug_bus_send_full('iteration', {full iteration payload})
    │   └── for each tool result:
    │       └── _debug_bus_send_full('tool_call', {full tool payload})
    └── _debug_bus_send_full('loop_end', {termination reason, duration})
```

### Live App Flow (OWL — read path)

```
User navigates to /ai-debug
    ↓
Bundle loads (JS + appropriate CSS bundle)
    ↓
main.js: mountComponent(AiDebugApp, document.body)
    → makeEnv() + startServices(env)
    → AiDebugApp.setup() → busService.addChannel('ai_debug')
    ↓
Agentic loop fires on another tab
    → bus.bus → WebSocket → browser
    → AiDebugApp handlers update state
    → OWL re-renders sidebar + detail panel
```

---

## Integration Points

### Theme Integration

| Component | Integration | Notes |
|-----------|-------------|-------|
| `color_scheme` cookie | Read in `controllers/main.py` | Set by Odoo enterprise webclient; fallback to `'light'` |
| `ai_debug.assets_dark` bundle | Includes `ai_debug.assets` + dark SCSS | JS not duplicated — loaded from base bundle with `t-css="false"` |
| Bootstrap CSS vars | Used in `app.scss` | Values baked in at Sass compile time; differ between light and dark bundles |

### Bus / Services Integration

| Service | Used by | Notes |
|---------|---------|-------|
| `bus_service` | `AiDebugApp` | WebSocket connection, channel subscription |
| `rpc` | Not used | No backend data fetching |
| `orm` | Not used | No DB models |

### Auth and Access

- Route: `auth='user'` — Odoo session required.
- Channel access: `ir.websocket` override restricts `ai_debug:*` channels to `group_system` (carried from v1.0).
- Any internal user can view the page; only system users receive bus events.

---

## Anti-Patterns

### Anti-Pattern 1: Using `prefers-color-scheme` CSS Media Query

**What people do:** Add `@media (prefers-color-scheme: dark) { ... }` in `app.scss` instead of a dark bundle.
**Why it's wrong:** Odoo's theme system is server-side bundle selection, not CSS media query. The user may have set Odoo to dark mode regardless of their OS preference. Using `prefers-color-scheme` would conflict with the user's Odoo preference.
**Do this instead:** Read the `color_scheme` cookie in the controller. Serve `assets_dark` when the cookie is `'dark'`. Use `var(--bs-*)` properties in SCSS — they resolve to the correct values for whichever bundle was loaded.

### Anti-Pattern 2: Storing Full Payload in pg_notify

**What people do:** Assume the bus payload flows through pg_notify directly and is size-limited.
**Why it's wrong:** The pg_notify size limit applies to the channel list, not the message content. Bus message data is stored in `bus_bus` rows as JSONB and fetched separately.
**Do this instead:** Send full payloads via `bus.bus._sendone()` without concern for pg_notify limits.

### Anti-Pattern 3: Including `web.assets_web` Instead of `web.assets_backend`

**What people do:** Build the dark bundle as `('include', 'web.assets_web')` to match the webclient pattern.
**Why it's wrong:** `web.assets_web` includes `web.assets_backend` plus `main.js` and `start.js` — those boot the full Odoo webclient and conflict with `mountComponent`.
**Do this instead:** Build `ai_debug.assets` with `('include', 'web.assets_backend')` as the base, then add the app-specific files. Match what `pos_self_order` does.

### Anti-Pattern 4: Duplicating JS in the Dark Bundle

**What people do:** Define `ai_debug.assets_dark` as a completely standalone bundle with all JS files repeated.
**Why it's wrong:** JS loads twice, bloating the page and causing `@odoo-module` double-registration errors.
**Do this instead:** Follow the webclient pattern exactly: load JS from the base bundle with `t-css="false"`, load CSS from the conditional bundle with `t-js="false"`.

### Anti-Pattern 5: Fetching Data On Selection

**What people do:** Store only IDs in state and fetch full data when the user clicks a node.
**Why it's wrong:** There is no DB to fetch from. All data must be in the bus payload, in memory, at selection time.
**Do this instead:** Store complete data in the state Map at event receipt time. Selection is purely a pointer into already-held state.

---

## Sources

**v1.2 theming sources (HIGH confidence — direct source reads):**

- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/models/ir_http.py` — `color_scheme()` method: reads cookie, then user setting; never returns `'system'`
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/controllers/home.py` — sets `color_scheme` cookie on every webclient response
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/models/ir_http.py` — base `color_scheme()` returns `"light"` hardcoded; `webclient_rendering_context()` adds it to QWeb context
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/views/webclient_templates.xml` — `web.webclient_bootstrap`: exact pattern of JS-only bundle + conditional CSS-only dark/light bundle
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/point_of_sale/views/pos_assets_index.xml` — POS uses `pos_color_scheme` cookie with same conditional `t-call-assets` pattern
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/__manifest__.py` — `web.assets_web_dark`: `('include', 'web.assets_web')` + `'web/static/src/**/*.dark.scss'`
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/__manifest__.py` — enterprise extends `web.assets_web_dark` with `web.dark_mode_variables`, dark SCSS helpers, and `**/*.dark.scss` files
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/lib/bootstrap/scss/_root.scss` — Bootstrap emits `--bs-body-bg`, `--bs-body-color`, `--bs-border-color` etc. on `:root` from Sass variables compiled at build time
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/static/src/scss/primary_variables.dark.scss` — inverted gray scale: gray-100 is darkest (`#1B1D26`), gray-900 is lightest (`#E4E4E4`)
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/static/src/webclient/navbar/navbar.dark.scss` — pattern for component dark overrides: override local CSS custom properties, not global Bootstrap vars
- `/Users/joseph/clones/odoo/custom/ai_debug/static/src/app/app.scss` — existing 650-line SCSS with hardcoded Catppuccin Mocha colors (all to be replaced)

**v1.1 base sources (HIGH confidence — direct source reads):**

- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/pos_self_order/views/pos_self_order.index.xml` — template structure
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/pos_self_order/controllers/self_entry.py` — controller pattern
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/env.js` — `mountComponent`, `makeEnv`, `startServices`
- `/Users/joseph/clones/odoo/custom/ai_debug/` — actual v1.1 module source (all files)

---
*Architecture research for: Odoo AI debugger v1.2 — native theming via Bootstrap CSS variables and conditional dark bundle*
*Researched: 2026-02-22*
