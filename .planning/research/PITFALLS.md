# Pitfalls Research

**Domain:** Native Odoo theming migration — hardcoded dark standalone OWL app to Bootstrap CSS variables
**Researched:** 2026-02-22
**Confidence:** HIGH (direct source inspection at all referenced paths)

This document is scoped to v1.2: replacing hardcoded Catppuccin Mocha colors with Odoo's Bootstrap CSS variables so the app respects the user's light/dark theme preference. The v1.1 pitfalls (bus architecture, DB migration) are superseded. This document focuses on CSS specificity conflicts, incomplete variable replacement, component-level color assumptions, asset bundle loading order, and theme-switching edge cases.

---

## Critical Pitfalls

### Pitfall 1: Controller Missing `color_scheme` — Template Renders Wrong Bundle Every Time

**What goes wrong:**

The current controller calls `request.env['ir.http'].session_info()` but does NOT call `webclient_rendering_context()`. The `color_scheme` variable is never passed to the template. When the template checks `t-if="color_scheme == 'dark'"`, the variable is undefined and evaluates falsy — the dark bundle is never loaded regardless of the user's preference. The app always loads the light bundle, making the theming feature appear to work only for one theme.

**Why it happens:**

`session_info()` and `color_scheme()` are separate methods on `ir.http`. The webclient template calls `webclient_rendering_context()` which bundles both. The existing `ai_debug` controller was written to get only `session_info` (which was all it needed for v1.1 bus authentication). Adding theming requires the second piece, but developers only remember to add the dark bundle conditional in the template, not the corresponding Python-side variable.

The enterprise `web_enterprise` module overrides `color_scheme()` to read from the `color_scheme` cookie AND `res.users.settings_id.color_scheme`. Without calling this method and passing its result to the template, the conditonal is always false.

**How to avoid:**

Change the controller to call `webclient_rendering_context()` instead of `session_info()` directly:

```python
# controllers/main.py — correct pattern
@http.route('/ai-debug', type='http', auth='user', readonly=True)
def ai_debug(self, **kw):
    if not is_user_internal(request.session.uid):
        return request.redirect('/web/login', 303)
    context = request.env['ir.http'].webclient_rendering_context()
    return request.render('ai_debug.index', context)
```

`webclient_rendering_context()` returns `{'color_scheme': ..., 'session_info': ...}`, so the template receives both variables in one call.

**Warning signs:**

- The dark bundle conditional in the template renders correctly in dev tools inspection but the app always shows light styles
- Logging `request.cookies.get('color_scheme')` in the controller shows `'dark'` but the dark bundle is not loaded
- Switching to dark in Odoo preferences has no effect on the debug app even after a hard reload

**Phase to address:** Phase 1 (Color scheme detection) — the first thing to fix before any CSS work

---

### Pitfall 2: Hardcoded Colors Override Bootstrap Variables via Specificity

**What goes wrong:**

The existing `app.scss` uses class selectors like `.ai-debug-app`, `.ai-debug-header`, `.ai-json-key`, etc. Bootstrap CSS custom properties (`--bs-body-bg`, `--bs-body-color`, `$body-bg`) are set on `body` or `:root`. When the hardcoded color declarations are simply left in place alongside the new Bootstrap variable declarations, the hardcoded values win because they are declared later in the cascade and are not less specific — they are on the same specificity level but come after the variables in the compiled CSS output order.

More critically: when the dark bundle (`web.assets_web_dark`) loads, it sets SCSS variables that compile to different hex values in its CSS output. But the hardcoded Catppuccin values in `app.scss` are not Bootstrap variables — they are literal hex strings. The dark bundle cannot override literal hex values. The app's custom classes remain Catppuccin-dark regardless of theme.

**Why it happens:**

Developers think "I'll use `var(--bs-body-bg)` for the main background and leave the rest for later." They replace a few properties but leave dozens of hardcoded hex values in the same file. When testing in dark mode (which matches the existing Catppuccin dark palette roughly), everything looks fine — the hardcoded dark values accidentally approximate the dark theme variables. The bug only manifests clearly in light mode, where `background-color: #1e1e2e` renders over a light Bootstrap background.

The current `app.scss` has approximately 40 distinct hardcoded color values spread across 650 lines. A partial replacement leaves an inconsistent mix that appears correct in dark mode but breaks in light mode.

**How to avoid:**

Replace ALL hardcoded color values in `app.scss` in a single pass before doing anything else. Use Odoo's SCSS variables (not CSS custom properties) because `app.scss` compiles in the same bundle as the rest of Odoo's SCSS:

```scss
// Replace this pattern:
background-color: #1e1e2e;    // Catppuccin Mantle
color: #cdd6f4;               // Catppuccin Text

// With Odoo SCSS variables:
background-color: $o-view-background-color;
color: $o-main-text-color;
```

Key Odoo SCSS variables available in both light and dark bundles (defined in `primary_variables.scss` and overridden in `primary_variables.dark.scss`):

| Catppuccin Color | Role | Odoo Variable |
|------------------|------|---------------|
| `#1e1e2e` (Base) | App background | `$o-view-background-color` |
| `#181825` (Mantle) | Header/darker bg | `$o-webclient-background-color` |
| `#313244` (Surface1) | Borders | `$border-color` |
| `#cdd6f4` (Text) | Primary text | `$o-main-text-color` |
| `#6c7086` (Overlay1) | Muted/dim text | `$o-gray-500` |
| `#585b70` (Overlay0) | Very muted text | `$o-gray-400` |
| `#89b4fa` (Blue) | Accent/selection | `$o-action` |
| `#a6e3a1` (Green) | Success | `$o-success` |
| `#f38ba8` (Red) | Error/danger | `$o-danger` |
| `#f9e2af` (Yellow) | Warning | `$o-warning` |
| `#fab387` (Peach) | Numbers | `$o-warning` |
| `#cba6f7` (Mauve) | Booleans | (no direct match — use `$o-info`) |

Do not mix SCSS variables and hardcoded hex in the same file. Complete the replacement before testing.

**Warning signs:**

- Running in light mode shows dark backgrounds on the app's own elements while Odoo chrome is light
- `grep -n "#[0-9a-f]\{3,6\}" app.scss` returns more than 0 results after the migration
- The sidebar tree rows show Catppuccin hover colors (`#2a2a3e`) over a white detail panel background

**Phase to address:** Phase 1 (Variable audit and replacement) — do this before the dark bundle conditional

---

### Pitfall 3: Notebook Component Dark Tab Overrides Conflict With App's Tab Overrides

**What goes wrong:**

The app's current `app.scss` (lines 357–392) manually overrides Notebook's `.nav-tabs` and `.nav-link` inside `.ai-debug-detail .o_notebook` with hardcoded Catppuccin colors. The enterprise `notebook.dark.scss` sets CSS custom properties on `.o_notebook` (e.g., `--Notebook__link-background-color: #{$o-gray-300}`). The enterprise notebook SCSS uses these custom properties via `var()` inside `notebook.scss`.

When both files are loaded:
1. `notebook.scss` sets the variables via CSS custom properties on `.o_notebook`
2. `notebook.dark.scss` overrides those custom properties for dark mode
3. `app.scss` then applies hardcoded hex values directly to `.nav-link`, bypassing the custom property mechanism entirely

The result: the Notebook tabs ignore the dark/light theme switch and remain hardcoded. In light mode, the dark Catppuccin tab colors look wrong against the now-themed page background.

**Why it happens:**

When the app was built (v1.1), the Notebook component didn't have native dark theme support that the app needed, so the developer wrote custom overrides. Now that the enterprise `notebook.dark.scss` properly handles dark theming via CSS custom properties, those overrides are redundant and conflicting. The developer migrating to native theming doesn't realize the conflict because testing in dark mode makes both approaches produce similar results.

**How to avoid:**

Remove the entire Notebook dark theme override block from `app.scss` (lines 357–392):

```scss
// DELETE this entire block — notebook.scss + notebook.dark.scss handle it natively:
.ai-debug-detail .o_notebook {
    .nav-tabs { ... }  // REMOVE
    .o_notebook_content { ... }  // REMOVE (or keep only layout rules, not color rules)
}
```

Keep only structural/layout rules (flex, overflow) and remove all color properties. Test both light and dark modes after removal to confirm the Notebook's native theming is adequate. If the native Notebook styles are insufficient (e.g., the tab indicator color is wrong in dark mode), create a dedicated `app.dark.scss` file following the Odoo pattern and set the CSS custom property variables there:

```scss
// app.dark.scss — only if needed
.ai-debug-detail .o_notebook {
    --Notebook__link-border-top-color--active: #{$o-action};
}
```

**Warning signs:**

- Notebook tabs render correctly in one theme but not the other after SCSS variable migration
- Browser devtools shows the `.nav-link` getting a background from `app.scss` that conflicts with `--Notebook__link-background-color`
- The active tab indicator (the colored top border) is the wrong color in one of the two modes

**Phase to address:** Phase 2 (Component-specific overrides) — after the main variable replacement

---

### Pitfall 4: `.o_dialog` Dark Overrides Conflict With Bootstrap Modal Variables

**What goes wrong:**

The current `app.scss` (lines 618–638) overrides `.o_dialog .modal-content` and `.o_dialog .modal-header` with hardcoded Catppuccin colors. Bootstrap 5 in Odoo uses CSS custom properties on `.modal-content` (`--bs-modal-bg`, `--bs-modal-color`, `--bs-modal-border-color`). The dark bundle (`bootstrap_overridden.dark.scss`) overrides these CSS custom properties for dark mode.

The hardcoded app override in `app.scss` sets `background-color: #1e1e2e` directly on `.modal-content`, which overrides the Bootstrap CSS custom property. This means:
- In dark mode: the hardcoded Catppuccin color and the Bootstrap dark color are similar, so no visible problem
- In light mode: the modal has a dark Catppuccin background on a light-themed page, making it look completely wrong

Additionally, the `.btn-close { filter: invert(1) }` hack (which was needed to make the close button visible on a dark background) will make the close button look wrong in light mode, where the button is already dark-colored.

**Why it happens:**

The `.o_dialog` override was added in a quick-fix (quick-11: "fix dialog title not legible dark text on dark background") and solved an immediate problem. The fix was correct for a hardcoded dark theme. It becomes a problem when the theme is now dynamic.

**How to avoid:**

Remove the color properties from the `.o_dialog` override block. Bootstrap 5's modal already has proper theming support via CSS custom properties. The dark bundle handles this automatically. Only keep structural overrides if needed:

```scss
// Keep only if structural layout is needed:
.o_dialog {
    // No color overrides needed — Bootstrap's --bs-modal-* variables handle theming
}
```

Remove `filter: invert(1)` from `.btn-close` — Bootstrap handles this in dark mode automatically via `$btn-close-color` and `$btn-close-filter` variables.

**Warning signs:**

- TextPopupDialog appears dark-on-dark or light-on-dark depending on mode
- The `X` close button in the dialog is invisible (too light) or inverted (too dark) in one of the two modes
- Browser devtools shows `background-color: #1e1e2e` from `app.scss` overriding `--bs-modal-bg` set by Bootstrap

**Phase to address:** Phase 2 (Component-specific overrides)

---

### Pitfall 5: Dark-Only Asset Bundle Approach — Light Mode Gets No Bundle, App Breaks

**What goes wrong:**

When implementing the conditional bundle loading in the template, developers copy the webclient pattern:

```xml
<t t-if="color_scheme == 'dark'">
    <t t-call-assets="ai_debug.assets_dark"/>  <!-- CSS only -->
</t>
<t t-else="">
    <t t-call-assets="ai_debug.assets"/>       <!-- Always loads -->
</t>
```

The mistake is structuring the bundle so that `ai_debug.assets` is the "base" bundle (no dark files) and `ai_debug.assets_dark` is a separate bundle that includes the dark overrides. But the current `ai_debug.assets` bundle uses `('include', 'web.assets_backend')` which already includes ALL Odoo CSS (light mode, with `('remove', 'web/static/src/**/*.dark.scss')` applied). Adding a separate dark bundle that includes `web.assets_web_dark` alongside `ai_debug.assets` causes the entire backend CSS to be compiled twice into two separate bundles — expensive and slow.

The correct approach (used by POS and the webclient) is:
- The main bundle (`ai_debug.assets`) loads JS and light CSS
- The dark bundle (`ai_debug.assets_dark`) uses `('include', 'ai_debug.assets')` PLUS dark overrides — it replaces the main bundle entirely in dark mode (not loads alongside it)

Looking at the webclient template (lines 311-319): it loads JS once via `t-js="true"` (implicitly) from `web.assets_web`, then loads CSS-only from either `web.assets_web_dark` or `web.assets_web` based on the scheme. The JS is only loaded once.

**How to avoid:**

Follow the exact webclient and POS pattern:

```xml
<!-- Template: always load JS from the base bundle (t-css="false") -->
<t t-call-assets="ai_debug.assets" t-css="false"/>

<!-- Conditionally load the right CSS bundle (t-js="false") -->
<t t-if="color_scheme == 'dark'">
    <t t-call-assets="ai_debug.assets_dark" media="screen" t-js="false"/>
</t>
<t t-else="">
    <t t-call-assets="ai_debug.assets" media="screen" t-js="false"/>
</t>
```

In `__manifest__.py`:

```python
'assets': {
    'ai_debug.assets': [
        ('include', 'web.assets_backend'),
        # Remove dark scss from the base bundle (light mode)
        ('remove', 'ai_debug/static/src/**/*.dark.scss'),
        'ai_debug/static/src/app/**/*.scss',
        'ai_debug/static/src/app/**/*.xml',
        'ai_debug/static/src/app/**/*.js',
    ],
    'ai_debug.assets_dark': [
        ('include', 'web.dark_mode_variables'),
        ('before', 'web_enterprise/static/src/scss/bootstrap_overridden.scss',
                   'web_enterprise/static/src/scss/bootstrap_overridden.dark.scss'),
        ('after', 'web/static/lib/bootstrap/scss/_functions.scss',
                  'web_enterprise/static/src/scss/bs_functions_overridden.dark.scss'),
        ('include', 'ai_debug.assets'),
        'web_enterprise/static/src/**/*.dark.scss',
        'ai_debug/static/src/**/*.dark.scss',  # your own dark overrides if any
    ],
    ...
}
```

**Warning signs:**

- Two full copies of Bootstrap CSS in the page (browser devtools shows duplicate `html, body { ... }` blocks)
- Asset bundle compilation takes noticeably longer after adding the dark bundle
- In dark mode, some Bootstrap elements have correct dark styling while others show double-applied styles causing visual glitches

**Phase to address:** Phase 1 (Asset bundle structure) — must be correct before any CSS work

---

### Pitfall 6: RGBA Hardcoded Colors Are Invisible to Simple `grep` Audit

**What goes wrong:**

The `app.scss` contains several hardcoded colors expressed as `rgba()` rather than hex, for example:

```scss
&.ai-diff-added { background-color: rgba(166, 227, 161, 0.1); }    // Catppuccin Green
&.ai-diff-removed { background-color: rgba(243, 139, 168, 0.1); }  // Catppuccin Red
&.ai-diff-changed { background-color: rgba(249, 226, 175, 0.1); }  // Catppuccin Yellow
.o_dialog .modal-backdrop { background: rgba(...); }
.ai-tree-row.ancestor { background-color: rgba(137, 180, 250, 0.05); } // Catppuccin Blue
```

An audit searching for `#[0-9a-f]{3,6}` will find the hex values but miss all the `rgba()` values. The developer declares "all hardcoded colors replaced" after fixing the hex values, ships the PR, and then discovers in light mode that the diff cells have barely-visible Catppuccin-green tint on a white background (since the RGB values map to Catppuccin colors, not Odoo colors).

**Why it happens:**

Semi-transparent colors (transparency composited over the background) were used intentionally because they let the background color show through. When using Catppuccin, this worked because the background was always dark. When the background becomes light, the same RGBA values produce a different visual result — the tint is more saturated and visible against white.

**How to avoid:**

Replace `rgba()` values using Odoo SCSS variable equivalents with opacity functions:

```scss
// Before:
background-color: rgba(166, 227, 161, 0.1);  // success tint on Catppuccin

// After:
background-color: rgba($o-success, 0.1);     // success tint using Odoo variable
// Or use Bootstrap's alpha utilities:
background-color: rgba(var(--bs-success-rgb), 0.1);
```

For the ancestor row highlight:
```scss
// Before:
background-color: rgba(137, 180, 250, 0.05);  // Catppuccin Blue

// After:
background-color: rgba($o-action, 0.05);       // Odoo action color
```

Run two grep passes during audit:
1. `grep -n "#[0-9a-fA-F]\{3,6\}"` for hex values
2. `grep -n "rgba\|rgb(" ` for RGB function calls

**Warning signs:**

- After variable migration, `grep -c "rgba\|rgb(" app.scss` returns more than 0
- In light mode, the state diff grid has colored cell backgrounds that look oversaturated
- The flash animation (`ai-tree-flash`) uses a hardcoded RGBA blue that doesn't match the new accent color

**Phase to address:** Phase 1 (Variable audit) — include rgba scan in the audit checklist

---

### Pitfall 7: `JsonTree` and `StateDiff` Rely on SCSS Classes With Hardcoded Colors — No Theme Awareness

**What goes wrong:**

`JsonTree` renders with classes like `.ai-json-key`, `.ai-json-string`, `.ai-json-number`, `.ai-json-boolean`, `.ai-json-null` that are styled in `app.scss` with hardcoded Catppuccin syntax colors. `StateDiff` uses `.ai-diff-cell.ai-diff-added` etc. with hardcoded RGBA background tints.

These components have no internal color logic — they just apply CSS classes. The colors are entirely controlled by SCSS. So if `app.scss` is fully migrated to Odoo variables, these components automatically get theme-aware colors. There is no JS-level change needed in `json_tree.js` or `state_diff.js`.

The pitfall is the inverse: developers assume the components have built-in theme awareness and skip migrating their SCSS rules. The classes are there; they work; the colors just happen to be wrong in light mode.

**Why it happens:**

Developers look at `json_tree.js` and `state_diff.js` and see no hardcoded colors — it's pure JS logic. They conclude "these components are theme-agnostic." They are, but only because their SCSS still has the hardcoded colors that need to be replaced.

**How to avoid:**

The components themselves do NOT need changes. Only `app.scss` does. Ensure the SCSS audit covers every rule that targets component-specific classes:

```scss
// These classes are entirely SCSS-driven — audit all of them:
.ai-json-key      → replace #89b4fa with $o-action
.ai-json-string   → replace #a6e3a1 with $o-success
.ai-json-number   → replace #fab387 with $o-warning
.ai-json-boolean  → replace #cba6f7 with $o-info
.ai-json-null     → replace #585b70 with $o-gray-400
.ai-json-preview  → replace #585b70 with $o-gray-400
.ai-diff-key      → replace #89b4fa with $o-action
.ai-diff-cell     → replace rgba() tints with rgba($o-success/danger/warning, 0.1)
```

For syntax highlighting in particular, Odoo has no dedicated syntax color tokens. Use the closest semantic color (success for strings, warning for numbers, info for booleans) — the result won't be identical to Catppuccin but will be coherent with the Odoo theme palette.

**Warning signs:**

- `json_tree.xml` or `state_diff.xml` are modified — they should not need any changes for theming
- JSON string values appear green in dark mode but the same green is barely visible in light mode
- The diff grid cells look correct in dark mode but wrong in light mode (hardcoded RGBA not adapted)

**Phase to address:** Phase 1 (Variable audit and replacement) — part of the SCSS pass

---

### Pitfall 8: The `color_scheme` Cookie Is Read-Only at Request Time — Real-Time Switching Requires Reload

**What goes wrong:**

The `color_scheme` cookie is set by Odoo when the user changes their theme preference in the user menu. The standalone app reads the cookie server-side at request time (in the Python controller) and bakes the choice into the HTML (which asset bundle to load). This means: if the user changes their Odoo theme while the debug app is open in another tab, the debug app does NOT update automatically — it continues showing whichever bundle was loaded at page load time. The user must reload the debug app tab manually.

This is expected and correct behavior (POS does the same thing). The pitfall is developers trying to implement real-time theme switching in the standalone app by reading `cookie.get("color_scheme")` in JavaScript and applying CSS classes dynamically — which does NOT work because the CSS bundles are already compiled and loaded as separate stylesheets. Dynamic class application cannot switch between entire compiled CSS bundles.

**Why it happens:**

The Odoo backend handles real-time theme switching via the `color_scheme_service` (enterprise only), which reloads the page when the color scheme changes. Developers see this behavior and try to replicate it in the standalone app without understanding the mechanism.

**How to avoid:**

Accept reload-on-switch as the correct behavior for the standalone app. Document this explicitly:
- The debug app inherits the theme from the user's Odoo preference at the time the page loads
- Changing the theme in Odoo requires reloading the debug app tab
- Do NOT attempt real-time in-app theme switching via JavaScript class manipulation

If real-time switching is wanted: reload the page when the `color_scheme` cookie changes. Listen for cookie changes via a polling interval or use the BroadcastChannel API (Odoo's color_scheme_service uses `localStorage` events for cross-tab coordination in the backend). For a developer tool, the reload approach is adequate.

**Warning signs:**

- JavaScript code reads `cookie.get("color_scheme")` and applies `document.body.classList.add('dark')` or similar — this will not swap CSS bundles
- A `color_scheme_service` import appears in the standalone app's JS — this service is part of `web_enterprise.webclient` and may not initialize correctly in a standalone app context
- Developer reports "I changed the theme but the debug app didn't update" — this is expected, not a bug, but must be documented

**Phase to address:** Phase 1 (Theme detection) — decide the UX (reload-required) before building anything

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Replace only hex colors and leave `rgba()` | Faster audit | RGBA tints use Catppuccin RGB values; appear wrong in light mode | Never — must audit rgba() too |
| Keep Notebook dark override block "just in case" | Avoids risk of visual regression | Conflicts with enterprise notebook.dark.scss; wrong colors in light mode | Never — test removal, use app.dark.scss if needed |
| Leave `.o_dialog` color overrides in place | Nothing breaks in dark mode | Light mode shows dark modal on light page | Never — Bootstrap handles modal theming |
| Replace main background but leave sub-component colors | Fast partial progress | Inconsistent theming — main bg is light but sidebars/panels are Catppuccin dark | Only if followed immediately by complete replacement |
| Read `color_scheme` cookie in JS and apply class | No page reload needed on switch | CSS bundle swap via class is impossible; compiled bundles are static | Never — accept reload-on-switch |
| Hardcode `ai_debug.assets_dark` to always include full `web.assets_backend_dark` | Simpler bundle definition | Double-compiles all Odoo CSS; asset compilation is significantly slower | Never — follow the `include ai_debug.assets` pattern |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Controller + `color_scheme` | Call `session_info()` only | Call `webclient_rendering_context()` which returns both `session_info` and `color_scheme` |
| Dark bundle structure | Make `ai_debug.assets_dark` a self-contained bundle | Make it use `('include', 'ai_debug.assets')` plus dark-only overrides, following POS pattern |
| Notebook theming | Write custom `.o_notebook .nav-tabs` overrides in `app.scss` | Remove color overrides entirely; enterprise `notebook.dark.scss` handles this via CSS custom properties |
| Bootstrap modal theming | Set `background-color` on `.modal-content` | Let Bootstrap's `--bs-modal-bg` CSS custom property do it; dark bundle overrides it automatically |
| SCSS variable scope | Use Bootstrap CSS custom properties (`var(--bs-body-bg)`) in SCSS | Use SCSS variables (`$o-view-background-color`) — they compile to the correct value per bundle |
| `app.dark.scss` location | Put dark overrides in `app.scss` behind a media query | Create a separate `app.dark.scss` file following the `.dark.scss` naming convention; the dark bundle includes it automatically via glob |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Dark bundle includes full `web.assets_backend` twice | Asset compilation takes 2–3x longer; page load has two full Bootstrap blocks | Use `('include', 'ai_debug.assets')` in the dark bundle (not `web.assets_backend`) | First run after adding the dark bundle to the manifest |
| All colors in one `app.scss` vs split light/dark | No performance issue | Creates maintainability debt — dark overrides mixed with light defaults | Not a runtime trap; only a maintenance issue |
| Checking `cookie.get("color_scheme")` on every render | Negligible for a developer tool | Cookie reads are synchronous and fast; not a performance concern at this scale | Never breaks at this scale |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Syntax highlight colors don't match Odoo palette | JSON tree colors look out-of-place in light mode (Catppuccin green on white is jarring) | Map Catppuccin colors to Odoo semantic equivalents (`$o-success` for strings, etc.) |
| Status dot colors hardcoded (connected=green, disconnected=red) | Status dot always shows Catppuccin green/red regardless of theme | Replace with `$o-success` and `$o-danger` — these are correctly themed |
| Flash animation uses hardcoded Catppuccin blue | New trace flash effect looks wrong against light background | Use `rgba($o-action, 0.3)` for the flash start color |
| "Looks dark on a dark page" passes visual QA | Developer tests in dark mode (matching current theme) and approves; light mode bugs escape | Always test BOTH modes after any CSS change — use a simple toggle script |
| No visual indication that the app theme follows Odoo settings | Developer confused why changing the app's appearance requires going to Odoo settings | Add a tooltip or help text noting the theme follows Odoo user preferences |

---

## "Looks Done But Isn't" Checklist

- [ ] **Complete variable replacement:** `grep -n "#[0-9a-fA-F]\{3,6\}\|rgba\|rgb(" app.scss` returns zero results after migration
- [ ] **Dark bundle loads in dark mode:** Open `/ai-debug` in dark mode; browser devtools Network tab shows two CSS bundle requests (one for base, one for `assets_dark`)
- [ ] **Light mode passes visual review:** Switch Odoo to light mode, reload `/ai-debug`, verify no dark backgrounds visible anywhere in the app UI
- [ ] **Notebook tabs themed correctly in both modes:** In light mode, inactive tabs have light background; in dark mode, they have `$o-gray-300` background — as defined by `notebook.dark.scss`
- [ ] **Dialog renders correctly in both modes:** Open TextPopupDialog in both modes; modal header, body, and close button all have appropriate colors for the theme
- [ ] **JsonTree syntax colors readable in both modes:** Verify string (green), number (orange), boolean (purple/blue), null (gray) are legible against both light and dark backgrounds
- [ ] **StateDiff tints visible in both modes:** Added/removed/changed cells show visible but subtle color tints in both light and dark backgrounds
- [ ] **Status dot uses correct Odoo colors:** Connected = `$o-success` green, Disconnected = `$o-danger` red — verify these look correct in both modes
- [ ] **Controller passes `color_scheme`:** Check rendered HTML source — the `<link>` tags should include the dark CSS bundle file when `color_scheme=dark` cookie is set
- [ ] **RGBA audit complete:** No `rgba(166,` or `rgba(243,` or `rgba(137,` or `rgba(249,` literal RGB values remain (these are Catppuccin RGB triples)

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Controller missing `color_scheme` | LOW | Add `webclient_rendering_context()` call; update template conditional; restart server |
| Partial variable replacement (hex done, rgba missed) | LOW | Run rgba audit; replace remaining rgba() values with `rgba($o-variable, opacity)` |
| Notebook override conflict | LOW | Delete color properties from the override block; test both modes |
| Dialog dark override conflicts | LOW | Delete color overrides from `.o_dialog` block; test both modes |
| Dark bundle double-compiles Odoo CSS | MEDIUM | Restructure the dark bundle to use `('include', 'ai_debug.assets')` instead of `('include', 'web.assets_backend')` |
| Tried real-time JS theme switching | MEDIUM | Remove JS theme switching code; implement page reload on cookie change instead |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Controller missing `color_scheme` | Phase 1: Theme detection | HTML source shows dark CSS `<link>` when cookie is dark |
| Asset bundle loads wrong bundle | Phase 1: Bundle structure | DevTools Network shows two CSS bundles in dark mode, one in light |
| Hex hardcoded colors not replaced | Phase 1: Variable audit | `grep "#[0-9a-f]\{3,6\}" app.scss` returns 0 results |
| RGBA hardcoded colors missed | Phase 1: Variable audit | `grep "rgba(1\|rgba(2\|rgba(9" app.scss` returns 0 results |
| Notebook override conflict | Phase 2: Component overrides | Notebook tabs correctly themed in both modes without app.scss color rules |
| Dialog dark override conflict | Phase 2: Component overrides | TextPopupDialog looks correct in both modes without app.scss color rules |
| JsonTree colors not adapted | Phase 1: Variable audit | JSON strings/numbers/booleans legible in both modes |
| StateDiff tints not adapted | Phase 1: Variable audit | Diff cells have subtle tints in both modes |
| Real-time switching attempted | Phase 1: Architecture decision | No `cookie.get("color_scheme")` in JS for visual switching; only reload-on-switch |
| Full audit misses rgba() | Phase 1: QA | Both grep passes return 0 after migration |

---

## Sources

- Direct source inspection: `/Users/joseph/clones/odoo/custom/ai_debug/static/src/app/app.scss` — 650 lines, ~40 hardcoded hex values, rgba() tints in diff grid and flash animation, Notebook + Dialog dark overrides
- Direct source inspection: `/Users/joseph/clones/odoo/custom/ai_debug/controllers/main.py` — current controller calls `session_info()` only, missing `color_scheme`
- Direct source inspection: `/Users/joseph/clones/odoo/custom/ai_debug/views/ai_debug_index.xml` — template has no `color_scheme` conditional, loads only `ai_debug.assets`
- Direct source inspection: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/models/ir_http.py` — `webclient_rendering_context()` returns both `color_scheme` and `session_info`; base `color_scheme()` always returns `"light"`
- Direct source inspection: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/models/ir_http.py` — enterprise override reads `color_scheme` cookie AND `res.users.settings_id.color_scheme`
- Direct source inspection: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/views/webclient_templates.xml` lines 311–319 — JS loaded once with `t-css="false"`; CSS loaded conditionally with `t-js="false"`
- Direct source inspection: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/point_of_sale/views/pos_assets_index.xml` — uses `request.cookies.get('pos_color_scheme') == 'dark'` conditional with separate `assets_prod_dark` bundle
- Direct source inspection: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/__manifest__.py` — `web.assets_backend` removes `*.dark.scss`; `web.assets_web_dark` includes `web.assets_web` plus all `*.dark.scss`
- Direct source inspection: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/__manifest__.py` — `web.dark_mode_variables` pattern; `web.assets_web_dark` uses `('include', 'web.dark_mode_variables')` plus dark SCSS files
- Direct source inspection: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/static/src/scss/primary_variables.dark.scss` — defines dark palette: `$o-gray-100: #1B1D26`, `$o-gray-200: #262A36`, `$o-view-background-color: $o-gray-200`, `$o-webclient-background-color: $o-gray-100`
- Direct source inspection: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/static/src/scss/primary_variables.scss` — defines light palette: `$o-gray-100: #F9FAFB`, `$o-gray-200: #e7e9ed`, `$o-view-background-color` (inherited from web module)
- Direct source inspection: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/static/src/core/notebook/notebook.dark.scss` — sets CSS custom properties `--Notebook__link-background-color`, `--Notebook__link-border-color` etc. on `.o_notebook`
- Direct source inspection: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/static/src/core/notebook/notebook.scss` — uses those custom properties via `var()` in `.nav-link`
- Direct source inspection: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/pos_enterprise/__manifest__.py` — `point_of_sale.assets_prod_dark` uses `('include', 'web.dark_mode_variables')` plus dark SCSS, confirming the pattern for standalone dark bundles

---
*Pitfalls research for: Odoo AI Debugger v1.2 — native Odoo theming migration*
*Researched: 2026-02-22*
