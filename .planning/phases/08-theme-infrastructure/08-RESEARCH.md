# Phase 8: Theme Infrastructure - Research

**Researched:** 2026-02-22
**Domain:** Odoo QWeb asset bundling, color_scheme cookie, ir.http extension
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**No-cookie fallback**
- Missing `color_scheme` cookie is treated the same as `color_scheme=light` — no dark bundle loaded
- No explicit fallback logic needed; the template simply doesn't render the dark `t-call-assets` when the value isn't "dark"
- Theme updates on next page load — if user changes theme in Odoo Preferences, the AI Debugger tab picks up the new cookie on refresh (no live switching)
- No console logging of resolved theme — the template context already contains `color_scheme` (success criteria #4), which is sufficient for debugging

**Dev/test workflow**
- Manual verification only — no automated Python tests for this infrastructure phase
- Verification can use either cookie manipulation in DevTools or Odoo Preferences toggle, whichever is practical
- Plan should include step-by-step manual verification instructions (DevTools Network tab, page source inspection) aligned with the success criteria
- Research and reference how Odoo's own web module (`webclient` template) handles dark mode CSS loading, and mirror that pattern

### Claude's Discretion
- Dark bundle contents for Phase 8 (whether to include a stub dark SCSS or just `web.dark_mode_variables`)
- Template conditional loading approach (t-call-assets with t-if vs other QWeb patterns)
- Controller implementation details for integrating `webclient_rendering_context()`

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| INFRA-01 | App reads user's `color_scheme` preference from cookie via `webclient_rendering_context()` in the controller | `ir.http.webclient_rendering_context()` returns `{'color_scheme': ..., 'session_info': ...}`; controller calls it and passes result as QWeb context |
| INFRA-02 | QWeb template conditionally loads dark or light CSS bundle based on `color_scheme` value | `t-if="color_scheme == 'dark'"` + `t-call-assets` with `t-js="false"` in template, mirroring `web.webclient_bootstrap` |
| INFRA-03 | Manifest defines `ai_debug.assets_dark` bundle that includes `web.dark_mode_variables` + dark SCSS overrides | Bundle uses `('include', 'web.dark_mode_variables')` then `('include', 'ai_debug.assets')`; no dark SCSS overrides needed in Phase 8 |
</phase_requirements>

## Summary

Phase 8 wires three things together: the controller reads the user's color scheme, passes it to the QWeb template via context, and the template uses it to conditionally load a second CSS-only bundle. The authoritative pattern to mirror is `web.webclient_bootstrap` in `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/views/webclient_templates.xml`.

The color scheme value comes from `request.env['ir.http'].webclient_rendering_context()`, which is already defined in `web/models/ir_http.py` and overridden by `web_enterprise/models/ir_http.py` to read from the `color_scheme` cookie (set when the user visits any `/odoo` or `/web` route). The base implementation in the community `web` module returns "light" unconditionally; the enterprise override reads the cookie and the user's saved `res.users.settings.color_scheme` field.

For Phase 8, the `ai_debug.assets_dark` bundle needs to exist in the manifest but can be minimal: include `web.dark_mode_variables` (the enterprise-defined variable overrides) and then `ai_debug.assets` (the full bundle). No dark SCSS overrides are needed yet — those are Phase 9. The bundle structure is CSS-compilable because `web.assets_backend` already removes all `*.dark.scss` files from the base bundle, so the light bundle is clean of dark CSS.

**Primary recommendation:** Mirror `web.webclient_bootstrap` exactly — JS-only load unconditionally, then CSS-only load conditionally by scheme. Define `ai_debug.assets_dark` in the manifest as `('include', 'web.dark_mode_variables')` + `('include', 'ai_debug.assets')`. Call `webclient_rendering_context()` in the controller instead of `session_info()` directly.

## Standard Stack

### Core

| Component | Location | Purpose | Why Standard |
|-----------|----------|---------|--------------|
| `ir.http.webclient_rendering_context()` | `web/models/ir_http.py` (base) + `web_enterprise/models/ir_http.py` (override) | Returns `{'color_scheme': str, 'session_info': dict}` | Authoritative method for resolving color scheme from cookie/user settings; already in `ir.http` inheritance chain |
| `t-call-assets` with `t-js="false"` | QWeb template directive | Emits only `<link>` tags (CSS) from the bundle, not `<script>` tags | Used by `web.webclient_bootstrap` to split JS and CSS loading |
| `t-call-assets` with `t-css="false"` | QWeb template directive | Emits only `<script>` tags (JS) from the bundle, not `<link>` tags | Used to load JS unconditionally, avoiding double-loading |
| `web.dark_mode_variables` | Bundle defined by `web_enterprise/__manifest__.py` | Named sub-bundle containing SCSS variable overrides for dark mode | Required first in any dark bundle so variables are defined before SCSS compilation |

### Supporting

| Component | Location | Purpose | When to Use |
|-----------|----------|---------|-------------|
| `color_scheme` cookie | Set by `web_enterprise/controllers/home.py` on every `/odoo` or `/web` response | Browser-side resolved color scheme | Read via `request.httprequest.cookies.get('color_scheme')` — already done by `ir.http.color_scheme()` |
| `media="screen"` attribute on `t-call-assets` | Template attribute | Restricts CSS link tag to screen media only | Used on the conditional dark/light CSS load in `web.webclient_bootstrap`; prevents print media double-loading |

## Architecture Patterns

### How Odoo's webclient_bootstrap Handles Dark Mode

Source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/views/webclient_templates.xml`, lines 311–319

```xml
<!-- JS-only, always loaded -->
<t t-call-assets="web.assets_web" t-css="false"/>

<!-- CSS-only, conditionally dark or light -->
<t t-if="color_scheme == 'dark'">
    <t t-call-assets="web.assets_web_dark" media="screen" t-js="false"/>
</t>
<t t-else="">
    <t t-call-assets="web.assets_web" media="screen" t-js="false"/>
</t>
```

**Why two calls for the same bundle?** The first `t-css="false"` call emits only `<script>` tags. The second `t-js="false"` call emits only `<link>` tags. Together they load JS once and CSS once (from whichever scheme bundle applies). The dark bundle contains all the same JS as the light bundle, so it would double-load JS if not filtered.

### Pattern: Controller — Pass Full webclient_rendering_context

Source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/controllers/home.py`, line 67

```python
context = request.env['ir.http'].webclient_rendering_context()
```

`webclient_rendering_context()` returns:
```python
{
    'color_scheme': self.color_scheme(),  # 'light' or 'dark'
    'session_info': self.session_info(),
}
```

The current controller calls `session_info()` directly and passes it explicitly:
```python
session_info = request.env['ir.http'].session_info()
return request.render('ai_debug.index', {'session_info': session_info})
```

The refactored controller should call `webclient_rendering_context()` and pass the whole context:
```python
context = request.env['ir.http'].webclient_rendering_context()
return request.render('ai_debug.index', context)
```

This makes `color_scheme` available in the template context automatically (success criteria #4).

### Pattern: Dark Bundle in Manifest

Source: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/__manifest__.py`

The enterprise pattern for a dark bundle that mirrors a base bundle:
```python
"web.assets_web_dark": [
    ('include', 'web.dark_mode_variables'),
    # web._assets_backend_helpers overrides
    ('before', '...scss', '...dark.scss'),
    # dark SCSS files
    'web_enterprise/static/src/**/*.dark.scss',
],
```

For Phase 8, `ai_debug.assets_dark` needs only:
```python
'ai_debug.assets_dark': [
    ('include', 'web.dark_mode_variables'),
    ('include', 'ai_debug.assets'),
],
```

No dark SCSS overrides yet — Phase 9 adds `ai_debug/static/src/app/app.dark.scss` by prepending it to this bundle.

### Pattern: Template Conditional Asset Load

The `ai_debug_index.xml` template currently:
```xml
<t t-call-assets="ai_debug.assets"/>
```

Must become:
```xml
<!-- JS-only, always loaded -->
<t t-call-assets="ai_debug.assets" t-css="false"/>

<!-- CSS-only, scheme-conditional -->
<t t-if="color_scheme == 'dark'">
    <t t-call-assets="ai_debug.assets_dark" media="screen" t-js="false"/>
</t>
<t t-else="">
    <t t-call-assets="ai_debug.assets" media="screen" t-js="false"/>
</t>
```

### Why web.dark_mode_variables, Not web.assets_backend

`web.assets_backend` explicitly removes all `*.dark.scss` files at the end of its definition:
```python
# Don't include dark mode files in light mode
('remove', 'web/static/src/**/*.dark.scss'),
```

If `ai_debug.assets_dark` re-included `web.assets_backend`, dark mode variables would be stripped again. The `web.dark_mode_variables` bundle is specifically designed to inject dark SCSS variables before the SCSS compilation that `ai_debug.assets` already includes via `web.assets_backend`.

### Anti-Patterns to Avoid

- **Including web.assets_backend in the dark bundle:** Would double-compile all backend CSS and strip dark variables. Use `('include', 'ai_debug.assets')` instead.
- **Calling session_info() directly in the refactored controller:** Loses the `color_scheme` key in context; call `webclient_rendering_context()` and spread the full dict.
- **Using t-if without t-else for CSS loading:** Would skip CSS entirely in light mode. Both branches must emit CSS.
- **Omitting t-js="false" on dark bundle load:** Would double-load all JS; the dark bundle includes all JS from the base bundle.
- **Using request.httprequest.cookies.get('color_scheme') in the controller directly:** Bypasses the `ir.http.color_scheme()` resolution chain which handles user settings and public user edge cases. Always go through `webclient_rendering_context()`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Reading color scheme from cookie | Custom cookie parsing in controller | `webclient_rendering_context()` via `ir.http` | Handles cookie + user settings + public user edge cases in one call |
| Splitting JS from CSS asset loads | Custom script/link tag generation | `t-css="false"` and `t-js="false"` on `t-call-assets` | QWeb built-in; handles debug mode, CDN, hashing automatically |
| Dark variable injection | Listing individual SCSS variables | `('include', 'web.dark_mode_variables')` | Enterprise-maintained bundle that stays in sync with `$o-gray-*` and other variable overrides |

## Common Pitfalls

### Pitfall 1: context passed to render() is missing color_scheme

**What goes wrong:** Template evaluates `color_scheme` as falsy/undefined; always loads light bundle.
**Why it happens:** Controller passes `{'session_info': session_info}` dict rather than the full `webclient_rendering_context()` return value.
**How to avoid:** Replace the two-step `session_info = ...; render(..., {'session_info': ...})` with `context = webclient_rendering_context(); render(..., context)`.
**Warning signs:** Success criteria #4 fails — page source does not contain `color_scheme` visible in template context.

### Pitfall 2: Dark bundle fails to compile because web.dark_mode_variables isn't populated

**What goes wrong:** Server error on page load when `color_scheme=dark` because the bundle resolves to an empty `web.dark_mode_variables`.
**Why it happens:** `web.dark_mode_variables` is populated by `web_enterprise`. If the module is not installed or `ai_debug` doesn't depend on `web_enterprise`, the bundle may be empty but shouldn't error.
**How to avoid:** The module already depends on `ai_app` which depends on enterprise modules. The bundle being empty is safe — it just means no variable overrides yet (Phase 9 adds them). Verify with `color_scheme=dark` cookie after restart.
**Warning signs:** HTTP 500 on `/ai-debug` with dark cookie; Odoo server log shows bundle compilation error.

### Pitfall 3: ai_debug.assets_dark defined before ai_debug.assets in the manifest

**What goes wrong:** `('include', 'ai_debug.assets')` inside `ai_debug.assets_dark` resolves to the not-yet-defined bundle.
**Why it happens:** Python dict ordering matters in manifest assets; both bundles are in the same `'assets'` dict.
**How to avoid:** Place `ai_debug.assets` key before `ai_debug.assets_dark` in the manifest dict. In practice, Odoo resolves these lazily, but keep ordering conventional.
**Warning signs:** Missing assets in the dark bundle; JS fails to load.

### Pitfall 4: Double JS load in dark mode

**What goes wrong:** DevTools shows two JS requests for the same scripts in dark mode.
**Why it happens:** Template loads `ai_debug.assets` without `t-css="false"` (full load) and then also loads `ai_debug.assets_dark` without `t-js="false"`.
**How to avoid:** Always pair `t-css="false"` on the unconditional load and `t-js="false"` on the conditional dark/light loads.
**Warning signs:** Success criteria #1 fails — dark mode shows two JS requests instead of one.

### Pitfall 5: session_info no longer passed to template

**What goes wrong:** Template fails with NameError on `session_info` because `webclient_rendering_context()` nests it under `context['session_info']` rather than top-level.
**Why it happens:** Existing template uses `<t t-out="json.dumps(session_info)"/>` inline. When controller switches to spreading `context`, `session_info` is still in context as `context['session_info']`.
**How to avoid:** No change needed — `webclient_rendering_context()` returns `{'color_scheme': ..., 'session_info': ...}` and QWeb receives both as top-level variables. The `session_info` key is preserved.
**Warning signs:** Odoo QWeb rendering error about undefined `session_info`.

## Code Examples

### Controller: Current vs Target

Current (`/Users/joseph/clones/odoo/custom/ai_debug/controllers/main.py`):
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
        return request.render('ai_debug.index', {
            'session_info': session_info,
        })
```

Target:
```python
from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.utils import is_user_internal


class AiDebugController(http.Controller):

    @http.route('/ai-debug', type='http', auth='user', readonly=True)
    def ai_debug(self, **kw):
        if not is_user_internal(request.session.uid):
            return request.redirect('/web/login', 303)
        context = request.env['ir.http'].webclient_rendering_context()
        return request.render('ai_debug.index', context)
```

### Manifest: New ai_debug.assets_dark Bundle

Add to `/Users/joseph/clones/odoo/custom/ai_debug/__manifest__.py` `'assets'` dict:
```python
'ai_debug.assets_dark': [
    ('include', 'web.dark_mode_variables'),
    ('include', 'ai_debug.assets'),
],
```

### Template: Conditional Asset Loading

Replace in `/Users/joseph/clones/odoo/custom/ai_debug/views/ai_debug_index.xml`:
```xml
<!-- Before -->
<t t-call-assets="ai_debug.assets"/>

<!-- After -->
<t t-call-assets="ai_debug.assets" t-css="false"/>
<t t-if="color_scheme == 'dark'">
    <t t-call-assets="ai_debug.assets_dark" media="screen" t-js="false"/>
</t>
<t t-else="">
    <t t-call-assets="ai_debug.assets" media="screen" t-js="false"/>
</t>
```

### Manual Verification Instructions

**Test 1 — Light mode (success criteria #1, #4):**
1. Open DevTools Network tab, filter by "ai_debug"
2. Delete the `color_scheme` cookie (or set it to "light")
3. Navigate to `/ai-debug`
4. Verify: one JS request for `ai_debug.assets`, one CSS request for `ai_debug.assets` (no `ai_debug.assets_dark` request)
5. Right-click → View Page Source; search for "color_scheme" — it should appear in the rendered template context

**Test 2 — Dark mode (success criteria #2, #3):**
1. Set `color_scheme=dark` cookie via DevTools Application tab → Cookies
2. Hard-refresh `/ai-debug`
3. Verify: one JS-only request from `ai_debug.assets`, one CSS-only request from `ai_debug.assets_dark`
4. No request for `web.assets_backend` as a standalone bundle (it's included inside `ai_debug.assets`)

**Cookie manipulation shortcut (DevTools console):**
```javascript
// Set dark
document.cookie = "color_scheme=dark; path=/";
location.reload();

// Set light
document.cookie = "color_scheme=light; path=/";
location.reload();
```

**Alternative: Odoo Preferences toggle**
Settings → Preferences → Color Scheme → Dark → Save. Then navigate to `/ai-debug`.

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Reading cookie directly in controller | Calling `webclient_rendering_context()` | Handles user settings override, public user guard, and future extension points |
| Single `t-call-assets` in template | Paired `t-css="false"` + conditional `t-js="false"` | Standard Odoo dark mode split; no JS double-load |
| `web.assets_web_dark` pattern (includes full base + dark.scss) | `('include', 'web.dark_mode_variables')` + `('include', 'ai_debug.assets')` | Avoids re-compiling all backend CSS; only injects dark variables into an existing compiled bundle |

## Open Questions

1. **Does web.dark_mode_variables resolve without error when empty?**
   - What we know: The bundle is populated by `web_enterprise` modules; if none of their variable files exist it would be empty
   - What's unclear: Whether an empty `('include', 'web.dark_mode_variables')` in `ai_debug.assets_dark` causes a server error or silently no-ops
   - Recommendation: Test by loading `/ai-debug?debug=assets` with `color_scheme=dark` cookie immediately after implementing Phase 8; if compilation fails, add a no-op comment SCSS file to the bundle as a stub

2. **Does webclient_rendering_context() require readonly=True on the route?**
   - What we know: The current route is `readonly=True`; `webclient_rendering_context()` calls `session_info()` which has substantial DB reads
   - What's unclear: Whether there are any write operations in `webclient_rendering_context()` that would conflict with `readonly=True`
   - Recommendation: Keep `readonly=True`; the method is read-only by design (it only reads user context, no writes)

## Sources

### Primary (HIGH confidence)

- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/views/webclient_templates.xml` — `web.webclient_bootstrap` template, lines 290–326: authoritative dark mode asset split pattern
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/models/ir_http.py` — `webclient_rendering_context()` and `color_scheme()` base implementation
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/models/ir_http.py` — `color_scheme()` enterprise override: cookie reading, user settings lookup
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/__manifest__.py` — `web.dark_mode_variables` and `web.assets_web_dark` bundle definitions
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/__manifest__.py` — `web.assets_backend` removes `*.dark.scss`; `web.assets_web_dark` includes base + dark
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/controllers/home.py` — enterprise sets `color_scheme` cookie on web_client responses
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/point_of_sale/views/pos_assets_index.xml` — POS standalone app dark mode pattern (analogous standalone app)
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/pos_enterprise/__manifest__.py` — `point_of_sale.assets_prod_dark` bundle: `('include', 'web.dark_mode_variables')` pattern

### Secondary (MEDIUM confidence)

None — all findings verified directly from source code.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — read directly from Odoo/enterprise source
- Architecture: HIGH — exact patterns extracted from webclient_templates.xml and ir_http.py
- Pitfalls: HIGH — derived from actual code paths and manifest definitions

**Research date:** 2026-02-22
**Valid until:** 90 days — Odoo asset system is stable; `webclient_rendering_context()` is well-established
