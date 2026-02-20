---
phase: quick-5
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/debug_panel/json_tree/json_tree.js
autonomous: true
requirements: [QUICK-5]

must_haves:
  truths:
    - "Ctrl/Cmd+click on a collapsed node expands it AND all descendants recursively"
    - "Ctrl/Cmd+click on an expanded node collapses it AND all descendants recursively"
    - "Normal click (no modifier) still toggles only the clicked node, children use depth-based defaults"
    - "Freshly mounted children (from expanding a collapsed parent) honor forceCollapsed prop"
  artifacts:
    - path: "ai_debug/static/src/debug_panel/json_tree/json_tree.js"
      provides: "Fixed JsonTree with mount-aware force propagation"
      contains: "forceCollapsed"
  key_links:
    - from: "setup()"
      to: "props.forceCollapsed"
      via: "initial state derivation"
      pattern: "props\\.forceCollapsed"
    - from: "toggle()"
      to: "state.childForceCollapsed"
      via: "reset to undefined on normal click"
      pattern: "childForceCollapsed.*undefined"
---

<objective>
Fix the broken Ctrl/Cmd+click recursive expand/collapse on JsonTree nodes.

Purpose: Ctrl+click was implemented in quick-3 but has a fundamental flaw — when a collapsed node is Ctrl+clicked to expand, its children are freshly mounted by OWL (not updated), so `onWillUpdateProps` never fires and children ignore the `forceCollapsed` prop. Deep children stay collapsed despite the recursive intent.

Output: Working recursive expand/collapse that handles both mount and update lifecycle paths.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/debug_panel/json_tree/json_tree.js
@ai_debug/static/src/debug_panel/json_tree/json_tree.xml
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix JsonTree setup() and toggle() for mount-aware force propagation</name>
  <files>ai_debug/static/src/debug_panel/json_tree/json_tree.js</files>
  <action>
Three changes in `json_tree.js`, all within the `JsonTree` class:

**Change 1 — setup(): Honor forceCollapsed on initial mount**

In `setup()`, after computing `depth` and `maxDepth`, check if `this.props.forceCollapsed` is a boolean (not undefined). If so, use it as the initial `collapsed` state instead of the depth-based default. Also propagate it downward by initializing `childForceCollapsed` and `childForceVersion` so that children mounted from this node also receive the force signal.

Replace the current state initialization block:
```js
this.state = useState({
    collapsed: depth >= maxDepth,
    childForceCollapsed: undefined,
    childForceVersion: 0,
});
```

With:
```js
const forceActive = typeof this.props.forceCollapsed === "boolean";
this.state = useState({
    collapsed: forceActive ? this.props.forceCollapsed : depth >= maxDepth,
    childForceCollapsed: forceActive ? this.props.forceCollapsed : undefined,
    childForceVersion: forceActive ? 1 : 0,
});
```

This ensures that when a child is freshly created (mounted) with `forceCollapsed=false`, it starts expanded and passes the force signal to its own children via `childForceCollapsed=false` and `childForceVersion=1`.

**Change 2 — toggle(): Reset childForceCollapsed on normal (non-Ctrl) clicks**

In the `toggle(ev)` method, add an `else` branch so that normal clicks (without Ctrl/Meta) reset `childForceCollapsed` to `undefined`. This ensures that after a recursive expand via Ctrl+click, a subsequent normal click on a child does NOT propagate stale force state — children will use their depth-based defaults when re-mounted.

Replace:
```js
toggle(ev) {
    this.state.collapsed = !this.state.collapsed;
    if (ev && (ev.ctrlKey || ev.metaKey)) {
        this.state.childForceCollapsed = this.state.collapsed;
        this.state.childForceVersion++;
    }
}
```

With:
```js
toggle(ev) {
    this.state.collapsed = !this.state.collapsed;
    if (ev && (ev.ctrlKey || ev.metaKey)) {
        // Recursive: force all descendants to match this node's new state
        this.state.childForceCollapsed = this.state.collapsed;
        this.state.childForceVersion++;
    } else {
        // Normal click: clear force so children use depth-based defaults
        this.state.childForceCollapsed = undefined;
    }
}
```

**No changes needed to the template (json_tree.xml)** — it already passes `state.childForceCollapsed` and `state.childForceVersion` to child JsonTree components.

**No changes needed to onWillUpdateProps** — it still handles the case where an already-mounted child receives updated props from a parent Ctrl+click.
  </action>
  <verify>
1. Open the AI Debug panel in Odoo with a trace that has deeply nested JSON (3+ levels).
2. Find a collapsed top-level node and Ctrl+click (or Cmd+click on Mac) to expand it.
3. Verify ALL descendant nodes expand recursively, not just the first level.
4. Ctrl+click the same node again to collapse — verify ALL descendants collapse.
5. Expand the node with a normal click (no modifier) — verify only that node expands, deep children stay collapsed per depth defaults.
6. After a Ctrl+click expand, normal-click a mid-level child to collapse and re-expand it — verify its children use depth-based defaults (not stuck in force-expanded state).
  </verify>
  <done>
Ctrl/Cmd+click recursively expands/collapses all descendant JsonTree nodes, including freshly mounted children. Normal clicks continue to toggle only the clicked node with depth-based defaults for children.
  </done>
</task>

</tasks>

<verification>
- Ctrl+click on collapsed node: all descendants expand (including deeply nested ones that were not in DOM)
- Ctrl+click on expanded node: all descendants collapse
- Normal click: only toggled node changes, children use depth defaults
- No JS console errors during any toggle operation
</verification>

<success_criteria>
Recursive expand/collapse works correctly in all scenarios: mount path (expanding collapsed node creates fresh children) and update path (already-mounted children receive new props). Normal clicks remain unaffected.
</success_criteria>

<output>
After completion, create `.planning/quick/5-fix-broken-ctrl-cmd-click-recursive-expa/5-SUMMARY.md`
</output>
