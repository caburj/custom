# Phase 2: Backend Views - Research

**Researched:** 2026-02-20
**Domain:** Odoo XML backend views — list, form, search views; badge widget; ace widget; menu items; computed display fields
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Trace list columns**
- Compact essentials: agent, model, state, iteration count, duration, date — 6 columns max
- State column uses badge widget with color coding (no row-level decoration-*)
- Default sort: newest first (create_date desc — matches model `_order`)
- Duration displayed as human-friendly format ("1.2s", "3m 42s") via computed field

**Drill-down flow**
- Trace → Iteration: One2many summary table on trace form; clicking opens iteration in its own form view
- Iteration → Tool Call: Same pattern — summary table; clicking opens tool call in its own form view
- Iteration summary table columns: index, duration, tool call count (minimal — just enough to pick which to open)
- Trace form uses tabbed notebook layout:
  - Tab 1: Iterations list
  - Tab 2: System prompt + RAG context
  - Tab 3: Error details (conditionally visible when state=error)

**JSON field display**
- Use Odoo's ace editor widget (`widget='ace'`) in JSON mode, read-only, for all JSON fields
- Add computed Text fields that `json.dumps(indent=2)` the raw Json fields for pretty-printed display
- Iteration form uses separate tabs: messages sent, raw response, state snapshots, tool calls
- Tool call form: args use ace/JSON widget; result uses plain text widget (result can be any string)

**Search & grouping**
- Search bar fields: agent, model, state, error_message (free-text)
- Default filters: "Errors" (state=error), "Today" (create_date=today)
- Group-by options: agent, model, state
- Tool call model gets its own search view with tool_name filter

### Claude's Discretion

- Exact field widths and form spacing
- Whether to add optional="hide" on any list columns
- Menu placement and naming within the Odoo backend
- Iteration and tool call list view column choices (beyond the decisions above)
- Ace editor height and configuration

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| VIEW-01 | Backend list and form views for `ai.debug.trace` with search/filter | Standard `ir.actions.act_window` + list/form/search XML views; badge widget for state; computed Char field for human-readable duration |
| VIEW-02 | Backend list and form views for `ai.debug.iteration` accessible from trace | One2many inline list on trace form + standalone form view; ace widget with `options="{'mode': 'json'}"` for JSON fields |
| VIEW-03 | Backend list and form views for `ai.debug.tool.call` accessible from iteration | Same One2many pattern; args ace/JSON; result plain text widget |
| VIEW-04 | Traces filterable by agent, model, date range, and error state | `<search>` view with `<field>` elements + `<filter>` for Errors and Today; `<group>` with group_by filters |
</phase_requirements>

---

## Summary

Phase 2 is standard Odoo backend view XML — no OWL, no JavaScript required. All three models (`ai.debug.trace`, `ai.debug.iteration`, `ai.debug.tool.call`) get list + form + search views, wired together via existing One2many relationships. The only Python work is adding computed display fields (human-readable duration, pretty-printed JSON Text fields) to the existing models so views can display them cleanly.

Patterns are all verified in enterprise source at `/Users/joseph/clones/odoo/enterprise/.worktrees/master-imp-ai-composable-prompts-jcb/`. Badge widget for colored state, ace widget with `options="{'mode': 'json'}"` for JSON, `invisible="state != 'error'"` for conditional notebook tab, `optional="hide"` for secondary list columns — all confirmed with multiple real-world examples.

The one non-trivial decision is the human-readable duration computed field. For millisecond-level durations ("1.2s", "3m 42s"), Odoo's `ir.qweb.field.duration` is designed for hours/minutes, not milliseconds. A simple Python helper in the model class is the right approach: `fields.Char(compute='_compute_duration_human')` that formats `total_duration_ms` into a concise string.

**Primary recommendation:** One XML file per model (3 view files + 1 menus file), add computed display fields to models, wire with `ir.actions.act_window`, place menu under Settings > Technical > AI Debug. No JavaScript needed for this phase.

---

## Standard Stack

### Core

| Element | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `ir.ui.view` (list, form, search) | Odoo master | All UI views | The Odoo XML view system — only supported way to define backend views |
| `ir.actions.act_window` | Odoo master | Open list/form for a model | Standard window action — required to make a view accessible |
| `menuitem` | Odoo master | Navigation menu entry | XML shorthand for `ir.ui.menu` records |
| `widget="badge"` | Odoo master | Colored pill for Selection fields | Verified in l10n_au, account_online_synchronization, pos views |
| `widget="ace"` with `options="{'mode': 'json'}"` | Odoo master | Code editor for JSON content | Verified in runbot config_views.xml and dockerfile_views.xml |
| `fields.Char(compute=...)` | Odoo master | Human-readable duration and JSON display | Standard computed field pattern |

### Supporting

| Element | Purpose | When to Use |
|---------|---------|-------------|
| `optional="hide"` on `<field>` in list | User-togglable column visibility | Secondary columns that clutter the list but may be useful |
| `<notebook>/<page>` with `invisible=` | Conditional tabs | Error details tab only when `state == 'error'` |
| `<separator/>` in search view | Visual separator between filter groups | Between type filters and group-by section |
| `nolabel="1"` on One2many fields | Suppress "Iterations" label above inline list | Standard for One2many inside a notebook page |

### No Installation Required

Everything is part of Odoo core. No `npm install`, no Python packages. Only XML + Python computed fields.

---

## Architecture Patterns

### Recommended File Structure for Phase 2

```
ai_debug/
├── __manifest__.py          (update: add views/*.xml to data list)
├── models/
│   ├── ai_debug_trace.py    (update: add _compute_duration_human, _compute_display_name)
│   ├── ai_debug_iteration.py (update: add _compute_* for JSON display and tool_call_count)
│   └── ai_debug_tool_call.py (update: add _compute_* for JSON display)
└── views/
    ├── ai_debug_trace_views.xml      (new: list + form + search for ai.debug.trace)
    ├── ai_debug_iteration_views.xml  (new: form + search for ai.debug.iteration)
    ├── ai_debug_tool_call_views.xml  (new: form + search for ai.debug.tool.call)
    └── menus.xml                     (new: menu items)
```

### Pattern 1: Badge Widget for Selection State

**What:** `widget="badge"` renders a Selection field as a colored pill. Use `decoration-*` attributes to map values to Bootstrap color classes.
**Available decorations:** `decoration-success` (green), `decoration-warning` (orange), `decoration-danger` (red), `decoration-info` (blue), `decoration-muted` (grey), `decoration-primary` (indigo)
**Works in:** Both list view columns and form view fields.

```xml
<!-- Source: verified in l10n_au_hr_payroll_account/views/l10n_au_stp_views.xml -->
<field name="state" widget="badge"
    decoration-success="state == 'done'"
    decoration-danger="state == 'error'"
    decoration-warning="state == 'paused'"
    decoration-info="state == 'running'"/>
```

State → color mapping for `ai.debug.trace`:
- `running` → `decoration-info` (blue, in-progress)
- `done` → `decoration-success` (green)
- `error` → `decoration-danger` (red)
- `paused` → `decoration-warning` (orange/yellow)

### Pattern 2: Ace Editor Widget for JSON Fields

**What:** `widget="ace"` renders a code editor. `options="{'mode': 'json'}"` enables JSON syntax highlighting. Use `readonly="1"` for display-only.
**Works for:** `fields.Text` (for the pretty-printed computed field). Cannot be used directly on `fields.Json` — see below.

```xml
<!-- Source: verified in runbot/views/config_views.xml -->
<field name="messages_sent_pretty" widget="ace" options="{'mode': 'json'}" readonly="1"/>
```

**Critical:** `fields.Json` stores native Python dict/list. The ace widget expects a string. Add a computed `fields.Text` field that calls `json.dumps(self.messages_sent, indent=2)` and display that computed field with `widget="ace"` instead of the raw Json field.

```python
# In ai_debug_iteration.py
messages_sent_pretty = fields.Text(
    string='Messages Sent (Pretty)',
    compute='_compute_messages_sent_pretty',
)

@api.depends('messages_sent')
def _compute_messages_sent_pretty(self):
    import json
    for record in self:
        record.messages_sent_pretty = (
            json.dumps(record.messages_sent, indent=2, ensure_ascii=False)
            if record.messages_sent else ''
        )
```

### Pattern 3: Human-Readable Duration Computed Field

**What:** Convert `total_duration_ms` (integer milliseconds) to a display string like "1.2s" or "3m 42s".
**Why not `ir.qweb.field.duration`:** That helper works with seconds (float). Requires conversion and is designed for hour/minute display, not sub-second values. A simple Python helper is cleaner and gives the exact format wanted ("1.2s", "3m 42s").

```python
# In ai_debug_trace.py
duration_human = fields.Char(
    string='Duration',
    compute='_compute_duration_human',
)

@api.depends('total_duration_ms')
def _compute_duration_human(self):
    for record in self:
        ms = record.total_duration_ms or 0
        if ms < 1000:
            record.duration_human = f"{ms}ms"
        elif ms < 60_000:
            record.duration_human = f"{ms / 1000:.1f}s"
        else:
            minutes = ms // 60_000
            seconds = (ms % 60_000) // 1000
            record.duration_human = f"{minutes}m {seconds}s"
```

Apply the same pattern for `duration_ms` on `ai.debug.iteration` and `ai.debug.tool.call`.

### Pattern 4: Conditional Notebook Tab (`invisible` on `<page>`)

**What:** Hide a notebook tab unless a condition is met. Use Python expression in `invisible` attribute.
**Odoo 17 syntax:** Domain-free string expression (not `attrs="{'invisible': [...]}"` which is Odoo 16 syntax).

```xml
<!-- Source: verified in runbot/views/build_error_views.xml -->
<notebook>
    <page string="Iterations">
        <field name="iteration_ids" nolabel="1">...</field>
    </page>
    <page string="System Prompt &amp; RAG">
        <field name="instructions" readonly="1"/>
        <field name="rag_context" readonly="1"/>
    </page>
    <page string="Error Details" invisible="state != 'error'">
        <field name="error_message" readonly="1"/>
        <field name="termination_reason" readonly="1"/>
    </page>
</notebook>
```

### Pattern 5: Search View with Filters, Date Range, and Group-By

```xml
<!-- Source: composite of verified patterns from runbot, ai module, enterprise -->
<search string="AI Debug Traces">
    <!-- Searchable fields -->
    <field name="agent_id"/>
    <field name="llm_model"/>
    <field name="state"/>
    <field name="error_message"/>
    <!-- Pre-built filters -->
    <separator/>
    <filter string="Errors" name="errors" domain="[('state', '=', 'error')]"/>
    <filter string="Today" name="today" domain="[('create_date', '&gt;=', 'today')]"/>
    <!-- Group by -->
    <separator/>
    <group expand="0" string="Group By">
        <filter string="Agent" name="group_by_agent" domain="[]" context="{'group_by': 'agent_id'}"/>
        <filter string="Model" name="group_by_model" domain="[]" context="{'group_by': 'llm_model'}"/>
        <filter string="State" name="group_by_state" domain="[]" context="{'group_by': 'state'}"/>
    </group>
</search>
```

**Date filter domain syntax (Odoo 17):** Use string relative dates like `'today'`, `'today -7d'` directly in domain. XML-escape `>` as `&gt;` and `<` as `&lt;`.

```xml
<!-- Verified: runbot/views/build_error_views.xml line 334 -->
<filter string="Today" name="today" domain="[('create_date', '&gt;=', 'today')]"/>
```

### Pattern 6: One2many Summary Table Drill-Down

**What:** Show child records in a list inside the parent's form; clicking opens the child's standalone form view.
**How Odoo handles the click:** By default, clicking a row in a One2many list view opens the child record in a dialog (modal). To open in its own full form view instead, use `open_target="new"` or rely on the child having its own `ir.actions.act_window` and using `<button>` actions.

**Standard pattern (opens in dialog, default):**
```xml
<field name="iteration_ids" nolabel="1">
    <list>
        <field name="index" string="#"/>
        <field name="duration_human"/>
        <field name="tool_call_count"/>
    </list>
</field>
```

Clicking a row in the inline list opens the row's form via the embedded form view (Odoo will use the One2many field's own form view or the model's default form view). This is the standard behavior and matches the drill-down requirement: click iteration row → iteration form.

**For the child form views to open as standalone pages** (not dialogs): define a standalone `ir.actions.act_window` for `ai.debug.iteration` and add a smart button or link from the trace form. However, since the CONTEXT.md says "clicking opens iteration in its own form view," the standard One2many dialog click is likely sufficient. If a full-page view is needed, add an `<act_window>` action and wire a button.

### Pattern 7: Tool Call Count Computed Field

The iteration summary table needs a "tool call count" column. Add a computed integer field:

```python
# In ai_debug_iteration.py
tool_call_count = fields.Integer(
    string='Tool Calls',
    compute='_compute_tool_call_count',
)

@api.depends('tool_call_ids')
def _compute_tool_call_count(self):
    for record in self:
        record.tool_call_count = len(record.tool_call_ids)
```

### Pattern 8: `ir.actions.act_window` with Default Search

```xml
<!-- Source: pattern from ai/views/ai_prompt_views.xml -->
<record id="action_ai_debug_trace" model="ir.actions.act_window">
    <field name="name">AI Debug Traces</field>
    <field name="res_model">ai.debug.trace</field>
    <field name="view_mode">list,form</field>
    <field name="context">{'search_default_today': 1}</field>
</record>
```

`search_default_{filter_name}` in context activates a filter by default on load.

### Pattern 9: Menu Structure

```xml
<!-- menus.xml pattern — place under Settings > Technical -->
<!-- Source: verified pattern from ai/module and runbot menus.xml -->

<!-- Root menu (under Settings > Technical, no parent needed if using base.menu_action_technical) -->
<menuitem
    id="menu_ai_debug_root"
    name="AI Debug"
    parent="base.menu_action_technical"
    sequence="100"/>

<menuitem
    id="menu_ai_debug_traces"
    name="Traces"
    parent="menu_ai_debug_root"
    action="action_ai_debug_trace"
    sequence="10"/>

<menuitem
    id="menu_ai_debug_iterations"
    name="Iterations"
    parent="menu_ai_debug_root"
    action="action_ai_debug_iteration"
    sequence="20"/>

<menuitem
    id="menu_ai_debug_tool_calls"
    name="Tool Calls"
    parent="menu_ai_debug_root"
    action="action_ai_debug_tool_call"
    sequence="30"/>
```

**Note on `base.menu_action_technical`:** This is the "Technical" sub-menu inside Settings. It is gated by `base.group_system` (admin). Since our models are also `base.group_system` only, placing the menu here is both natural and ensures non-admins never see the menu items.

### Anti-Patterns to Avoid

- **Using `attrs="{'invisible': [...]}"` (Odoo 16 syntax):** Odoo 17/master uses plain Python expression strings in `invisible=`, `readonly=`, `required=`. The old `attrs` dict format is deprecated and will trigger warnings.
- **Displaying `fields.Json` directly with `widget="ace"`:** The ace widget expects a string. A `fields.Json` field stores a Python dict/list; displaying it directly would show the Python repr, not formatted JSON. Always add an intermediate computed `fields.Text` field.
- **Using `decoration-*` on list `<list>` element itself for state-based row coloring:** The CONTEXT.md explicitly says to use badge widget on the state column, not row-level `decoration-*`. Row-level decorations apply to ALL text in the row; badge is cleaner for a single state column.
- **`<field>` inside `<form>` without `<sheet>`:** Modern Odoo forms use `<sheet>` to get the proper card-style layout. Without it, the form renders as a flat list.
- **Omitting `readonly="1"` on computed fields in form views:** Odoo will attempt to write computed fields if they're editable; while ORM blocks this, it's cleaner and correct to mark them readonly in the view.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON display in forms | Custom HTML widget or QWeb | `widget="ace"` on computed Text field | Ace widget provides syntax highlighting, copy/paste, scroll — free with Odoo |
| State color coding | Manual CSS classes | `widget="badge"` + `decoration-*` | Bootstrap utility classes, consistent with Odoo UI, zero CSS needed |
| List column toggle | JS to show/hide columns | `optional="hide"` on `<field>` | Built-in Odoo list column visibility toggle — users can show/hide from column headers |
| Date range filtering | Custom JS date picker | `filter` with `'today'` domain strings | Odoo's domain engine evaluates relative date strings server-side |
| Duration formatting | `ir.qweb.field.duration` for ms values | Simple computed `fields.Char` | `ir.qweb.field.duration` expects seconds and formats as "X hours Y minutes" — wrong granularity for ms |

---

## Common Pitfalls

### Pitfall 1: `fields.Json` Cannot Be Displayed Directly with Ace Widget

**What goes wrong:** Adding `widget="ace"` to a `fields.Json` field in the XML — the ace widget sees a Python dict/list object, not a string, and either errors or shows `[object Object]`.
**Why it happens:** `fields.Json` stores and returns Python native types (dict, list). The ace widget in text mode expects a string.
**How to avoid:** Always add an intermediate computed `fields.Text` field that calls `json.dumps(value, indent=2)`. Display the computed Text field, not the raw Json field.
**Warning signs:** Ace editor shows garbled output or JavaScript console errors about unexpected type.

### Pitfall 2: Odoo 17 `invisible` Syntax vs Odoo 16 `attrs`

**What goes wrong:** Writing `attrs="{'invisible': [('state', '!=', 'error')]}"` — this is the Odoo 16 syntax. In Odoo 17 (master), this raises a deprecation warning and may not work.
**Why it happens:** Odoo 17 changed to plain Python expression strings: `invisible="state != 'error'"`.
**How to avoid:** Use `invisible="..."` with a Python expression string. No `attrs` dict needed.
**Warning signs:** Server log warnings about deprecated `attrs` format on view load.

### Pitfall 3: `_rec_name` Missing on Debug Models

**What goes wrong:** The debug models have no `name` field and no `_rec_name` override. Odoo uses `display_name` which defaults to `id` (e.g., "ai.debug.trace(42,)"). This makes Many2one dropdowns and form titles ugly.
**Why it happens:** Models without `name` field get `id` as display name by default.
**How to avoid:** Add `_rec_name = 'display_name'` plus a `display_name = fields.Char(compute=...)` that builds a meaningful name like `"Trace #42 — gpt-4o — 2026-02-20"`. Or override `name_get()` (deprecated in Odoo 17 — use computed `_rec_name` field instead).
**Odoo 17 approach:** Define a computed `fields.Char` named something like `display_name` (note: `display_name` is a magic field in Odoo — use a different name like `label` or just override `_rec_name` to point to an existing meaningful field like `agent_id` with fallback to `create_date`).

**Practical fix for ai.debug.trace:**
```python
_rec_name = 'agent_id'  # Many2one — Odoo will use agent's name; falls back gracefully
```

For `ai.debug.iteration`: `_rec_name = 'index'` (shows the iteration number).
For `ai.debug.tool.call`: `_rec_name = 'tool_name'`.

### Pitfall 4: `base.menu_action_technical` Requires Odoo Technical Menu to Be Visible

**What goes wrong:** Placing menus under `base.menu_action_technical` but the Technical menu in Settings is only visible with developer mode OR the user has debug/developer access.
**Why it happens:** `Settings > Technical` is only shown in developer mode or to admins with the right groups.
**How to avoid:** This is fine for our use case — the CONTEXT.md specifies admin-only access (`base.group_system`), and admins always have access to Technical menus. No action needed.

### Pitfall 5: One2many Dialog vs. Full-Page Form for Drill-Down

**What goes wrong:** Clicking an iteration row in the trace form opens a dialog/modal instead of a full form page.
**Why it happens:** Odoo's default One2many row click opens a dialog using the embedded form view. This is the standard behavior.
**How to avoid:** For this developer tool, the dialog behavior is acceptable and matches the requirement ("clicking opens iteration in its own form view" — a dialog IS a form view). If full-page navigation is explicitly required, add an `<act_window>` action for iterations and link it via `type="object"` button or `open_target="current"`. Research suggests dialog is the standard and expected behavior for One2many drill-down.
**Decision point for planner:** The CONTEXT.md says "clicking opens iteration in its own form view" — confirm whether dialog (standard) or full-page navigation is intended. If dialog is acceptable, no extra work needed. If full-page: add `<act_window>` actions for iteration and tool_call models.

### Pitfall 6: Manifest Must Reference All View XML Files

**What goes wrong:** Adding XML view files but forgetting to add them to `__manifest__.py` `data` list. The views won't load.
**Why it happens:** Odoo only loads files explicitly listed in `data`.
**How to avoid:** Every new `.xml` file MUST appear in `__manifest__.py` `data` in load order: security first, then data, then views.

```python
'data': [
    'security/ir.model.access.csv',
    'views/ai_debug_trace_views.xml',
    'views/ai_debug_iteration_views.xml',
    'views/ai_debug_tool_call_views.xml',
    'views/menus.xml',  # menus last — they reference actions defined in view files
],
```

### Pitfall 7: Tool Call Count Depends on `tool_call_ids` Traversal — May Need `read_group` for Performance

**What goes wrong:** `tool_call_count = len(self.tool_call_ids)` runs a SELECT for every iteration when displaying the iteration summary list in a trace form. With 20 iterations × N tool calls, this is N+1 queries.
**Why it happens:** Computed fields with `depends('tool_call_ids')` trigger a read of the entire One2many set per record.
**How to avoid:** Use `_read_group` to batch the count:

```python
@api.depends('tool_call_ids')
def _compute_tool_call_count(self):
    counts = {
        data['iteration_id'][0]: data['__count']
        for data in self.env['ai.debug.tool.call']._read_group(
            [('iteration_id', 'in', self.ids)],
            ['iteration_id'],
            ['__count'],
        )
    } if self.ids else {}
    for record in self:
        record.tool_call_count = counts.get(record.id, 0)
```

This is a developer tool with typically small data sets (7-day retention), so N+1 may be acceptable. The planner should decide whether to use simple `len()` or `_read_group`.

---

## Code Examples

Verified patterns from Odoo master source:

### Complete Trace List View

```xml
<!-- Source: composite of badge pattern + optional="hide" + create_date sort -->
<record id="view_ai_debug_trace_list" model="ir.ui.view">
    <field name="name">ai.debug.trace.list</field>
    <field name="model">ai.debug.trace</field>
    <field name="arch" type="xml">
        <list string="AI Debug Traces">
            <field name="create_date" string="Date" optional="hide"/>
            <field name="agent_id"/>
            <field name="llm_model" string="Model"/>
            <field name="state" widget="badge"
                decoration-info="state == 'running'"
                decoration-success="state == 'done'"
                decoration-danger="state == 'error'"
                decoration-warning="state == 'paused'"/>
            <field name="iteration_count" string="Iterations"/>
            <field name="duration_human" string="Duration"/>
        </list>
    </field>
</record>
```

### Trace Form View (Notebook with Conditional Error Tab)

```xml
<!-- Source: notebook/page pattern from runbot bundle_views.xml + invisible from build_error_views.xml -->
<record id="view_ai_debug_trace_form" model="ir.ui.view">
    <field name="name">ai.debug.trace.form</field>
    <field name="model">ai.debug.trace</field>
    <field name="arch" type="xml">
        <form string="AI Debug Trace">
            <sheet>
                <group>
                    <group>
                        <field name="agent_id" readonly="1"/>
                        <field name="llm_model" readonly="1"/>
                        <field name="state" widget="badge"
                            decoration-info="state == 'running'"
                            decoration-success="state == 'done'"
                            decoration-danger="state == 'error'"
                            decoration-warning="state == 'paused'"
                            readonly="1"/>
                        <field name="termination_reason" readonly="1"/>
                    </group>
                    <group>
                        <field name="start_time" readonly="1"/>
                        <field name="duration_human" string="Duration" readonly="1"/>
                        <field name="iteration_count" readonly="1"/>
                    </group>
                </group>
                <notebook>
                    <page string="Iterations">
                        <field name="iteration_ids" nolabel="1" readonly="1">
                            <list>
                                <field name="index" string="#"/>
                                <field name="duration_human" string="Duration"/>
                                <field name="tool_call_count" string="Tool Calls"/>
                            </list>
                        </field>
                    </page>
                    <page string="System Prompt &amp; RAG">
                        <field name="instructions" readonly="1"/>
                        <field name="rag_context" readonly="1"/>
                    </page>
                    <page string="Error Details" invisible="state != 'error'">
                        <field name="error_message" readonly="1"/>
                    </page>
                </notebook>
            </sheet>
        </form>
    </field>
</record>
```

### Trace Search View

```xml
<!-- Source: search pattern from ai/views/ai_prompt_views.xml + date filter from enterprise -->
<record id="view_ai_debug_trace_search" model="ir.ui.view">
    <field name="name">ai.debug.trace.search</field>
    <field name="model">ai.debug.trace</field>
    <field name="arch" type="xml">
        <search string="AI Debug Traces">
            <field name="agent_id"/>
            <field name="llm_model" string="Model"/>
            <field name="state"/>
            <field name="error_message"/>
            <separator/>
            <filter string="Errors" name="errors" domain="[('state', '=', 'error')]"/>
            <filter string="Today" name="today" domain="[('create_date', '&gt;=', 'today')]"/>
            <separator/>
            <group expand="0" string="Group By">
                <filter string="Agent" name="group_by_agent" domain="[]" context="{'group_by': 'agent_id'}"/>
                <filter string="Model" name="group_by_model" domain="[]" context="{'group_by': 'llm_model'}"/>
                <filter string="State" name="group_by_state" domain="[]" context="{'group_by': 'state'}"/>
            </group>
        </search>
    </field>
</record>
```

### Ace Widget for JSON Pretty-Print (Iteration Form)

```xml
<!-- Source: ace widget pattern from runbot/views/config_views.xml -->
<page string="Messages Sent">
    <field name="messages_sent_pretty" widget="ace" options="{'mode': 'json'}" readonly="1" nolabel="1"/>
</page>
<page string="Raw Response">
    <field name="raw_response_pretty" widget="ace" options="{'mode': 'json'}" readonly="1" nolabel="1"/>
</page>
```

### Computed Pretty-Print Fields (Python)

```python
# Source: pattern combining fields.Text compute + json.dumps
import json

class AiDebugIteration(models.Model):
    _name = 'ai.debug.iteration'

    messages_sent_pretty = fields.Text(
        compute='_compute_messages_sent_pretty',
        string='Messages Sent (Formatted)',
    )
    raw_response_pretty = fields.Text(
        compute='_compute_raw_response_pretty',
        string='Raw Response (Formatted)',
    )
    state_before_pretty = fields.Text(
        compute='_compute_state_pretty',
        string='State Before (Formatted)',
    )
    state_after_pretty = fields.Text(
        compute='_compute_state_pretty',
        string='State After (Formatted)',
    )
    tool_call_count = fields.Integer(
        compute='_compute_tool_call_count',
        string='Tool Calls',
    )
    duration_human = fields.Char(
        compute='_compute_duration_human',
        string='Duration',
    )

    @api.depends('messages_sent')
    def _compute_messages_sent_pretty(self):
        for r in self:
            r.messages_sent_pretty = json.dumps(r.messages_sent, indent=2, ensure_ascii=False) if r.messages_sent else ''

    @api.depends('raw_response')
    def _compute_raw_response_pretty(self):
        for r in self:
            r.raw_response_pretty = json.dumps(r.raw_response, indent=2, ensure_ascii=False) if r.raw_response else ''

    @api.depends('state_before', 'state_after')
    def _compute_state_pretty(self):
        for r in self:
            r.state_before_pretty = json.dumps(r.state_before, indent=2, ensure_ascii=False) if r.state_before else ''
            r.state_after_pretty = json.dumps(r.state_after, indent=2, ensure_ascii=False) if r.state_after else ''

    @api.depends('tool_call_ids')
    def _compute_tool_call_count(self):
        for r in self:
            r.tool_call_count = len(r.tool_call_ids)

    @api.depends('duration_ms')
    def _compute_duration_human(self):
        for r in self:
            ms = r.duration_ms or 0
            if ms < 1000:
                r.duration_human = f"{ms}ms"
            elif ms < 60_000:
                r.duration_human = f"{ms / 1000:.1f}s"
            else:
                minutes = ms // 60_000
                seconds = (ms % 60_000) // 1000
                r.duration_human = f"{minutes}m {seconds}s"
```

### Badge Widget Color Mapping Verified

```xml
<!-- Source: verified in account_online_synchronization/wizard/account_bank_statement_line.xml -->
<field name="state" widget="badge"
    decoration-muted="state == 'pending'"
    decoration-success="state == 'posted'"/>

<!-- Source: verified in l10n_au_hr_payroll_account/views/l10n_au_stp_views.xml -->
<field name="state" widget="badge"
    decoration-success="state == 'sent'"
    decoration-info="state == 'ready'"
    decoration-warning="state == 'error'"/>
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `attrs="{'invisible': [...]}"` | `invisible="python_expr"` | Odoo 17 | Simpler syntax; `attrs` is deprecated |
| `name_get()` override for display | Computed `_rec_name` field | Odoo 17 | `name_get()` deprecated; use computed char field |
| `<tree>` tag for list views | `<list>` tag | Odoo 17 | `<tree>` still works but `<list>` is current |
| `<field widget="ace">` on Text field | Same — unchanged | — | Ace widget API is stable |
| `decoration-*` on `<tree>` element | `widget="badge"` on state field | Odoo 16/17 | Row-level coloring vs. per-cell badge — badge is the current preference |

**Deprecated/outdated (verified in Odoo 17 source):**
- `<tree>`: Works but emit deprecation warning in some versions; use `<list>`
- `attrs=`: Deprecated; use direct `invisible=`, `readonly=`, `required=` attributes
- `name_get()`: Deprecated; override `_compute_display_name` or set `_rec_name`

---

## Open Questions

1. **One2many drill-down: dialog or full-page navigation?**
   - What we know: Default Odoo One2many row click opens a dialog (modal form). CONTEXT.md says "clicking opens iteration in its own form view."
   - What's unclear: Whether "its own form view" means a dialog (which is still a form view) or full-page navigation.
   - Recommendation: Implement standard dialog behavior first (zero extra work). Add `ir.actions.act_window` for standalone navigation only if the user explicitly requests full-page drill-down. The planner should flag this for clarification or make a documented discretion call.

2. **`_rec_name` for iteration and tool_call — integer fields as record names**
   - What we know: `_rec_name = 'index'` on iteration would show "0", "1", "2" as record names in Many2one dropdowns. `_rec_name = 'tool_name'` on tool_call is reasonable.
   - What's unclear: Whether any Many2one references to these models will exist in Phase 2 views (they don't — all access is via One2many from parent).
   - Recommendation: `_rec_name` is only relevant if these models appear in Many2one fields. Since Phase 2 access is purely via One2many, skip `_rec_name` customization for now. The planner should note this as deferred unless a display issue appears.

3. **Menu placement: `base.menu_action_technical` vs. standalone top-level menu**
   - What we know: The Phase 1 CONTEXT.md says "Settings > Technical > AI Debug." The existing STACK.md confirms this placement.
   - What's unclear: Whether `base.menu_action_technical` is the correct parent XML ID.
   - Recommendation: Use `parent="base.menu_action_technical"` — this is the Technical sub-menu inside Settings, gated by `base.group_system`. Verified via runbot menus.xml pattern (runbot has its own root menu but the Technical parent is standard for small internal tools).

---

## Sources

### Primary (HIGH confidence)

- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-imp-ai-composable-prompts-jcb/l10n_au_hr_payroll_account/views/l10n_au_stp_views.xml` — `widget="badge"` with `decoration-*` attributes on Selection state field in list view
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-imp-ai-composable-prompts-jcb/account_online_synchronization/wizard/account_bank_statement_line.xml` — `widget="badge"` with `decoration-muted`, `decoration-success`
- `/Users/joseph/clones/odoo/runbot/runbot/views/config_views.xml` — `widget="ace"` with `options="{'mode': 'json'}"` and `options="{'mode': 'python'}"`
- `/Users/joseph/clones/odoo/runbot/runbot/views/dockerfile_views.xml` — `widget="ace"` for text content fields
- `/Users/joseph/clones/odoo/runbot/runbot/views/bundle_views.xml` — `<notebook>/<page>` with `<list>` (One2many), `optional="hide"`, actions/menus wiring
- `/Users/joseph/clones/odoo/runbot/runbot/views/build_error_views.xml` — `<page>` with `invisible=` (conditional tab), `groups=` on page
- `/Users/joseph/clones/odoo/runbot/runbot/views/build_views.xml` — search view with `<filter>` + `group_by` context
- `/Users/joseph/clones/odoo/runbot/runbot/views/menus.xml` — menu item hierarchy with `parent=`, `action=`, `sequence=`
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-imp-ai-composable-prompts-jcb/ai/views/ai_prompt_views.xml` — complete list + form + search + action + menu pattern from the `ai` module itself
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-imp-ai-composable-prompts-jcb/appointment/models/appointment_type.py` — `_compute_appointment_duration_formatted` for duration display reference
- Phase 1 Research (`01-RESEARCH.md`) — confirmed model field definitions, `_order`, access CSV format

### Secondary (MEDIUM confidence)

- `runbot/runbot/views/build_error_views.xml` lines 334/370 — `domain="[('log_date', '&gt;', 'today -1d')]"` date filter pattern; verified it works as relative date string

---

## Metadata

**Confidence breakdown:**
- Standard stack (XML views, badge, ace): HIGH — all patterns verified in actual Odoo enterprise source code
- Architecture (file structure, computed fields, drill-down): HIGH — follows established patterns; one open question (dialog vs full-page) is a UX choice, not a technical uncertainty
- Pitfalls: HIGH — identified from direct inspection of Odoo 17 deprecations and widget behavior

**Research date:** 2026-02-20
**Valid until:** 2026-03-20 (Odoo XML view APIs are stable; badge/ace widgets don't change between minor versions)
