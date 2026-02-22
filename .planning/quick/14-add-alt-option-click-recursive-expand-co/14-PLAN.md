---
phase: quick-14
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/detail/json_tree.js
  - ai_debug/static/src/app/detail/json_tree.xml
autonomous: true
requirements: [QUICK-14]

must_haves:
  truths:
    - "Alt/Option+click on a collapsed node recursively expands it and all descendants"
    - "Alt/Option+click on an expanded node recursively collapses it and all descendants"
    - "Normal click (without Alt) toggles only the clicked node, unchanged from current behavior"
    - "After a recursive expand, normal-clicking a single child toggles only that child independently"
  artifacts:
    - path: "ai_debug/static/src/app/detail/json_tree.js"
      provides: "Recursive expand/collapse via Alt+click using forceCollapsed/forceVersion prop signaling"
      contains: "altKey"
    - path: "ai_debug/static/src/app/detail/json_tree.xml"
      provides: "Passes forceCollapsed and forceVersion props to child JsonTree components"
      contains: "forceCollapsed"
  key_links:
    - from: "json_tree.js toggle(ev)"
      to: "state.childForceCollapsed / state.childForceVersion"
      via: "ev.altKey detection sets childForceCollapsed and increments childForceVersion"
      pattern: "ev\\.altKey"
    - from: "json_tree.js onWillUpdateProps"
      to: "state.collapsed / childForceCollapsed / childForceVersion"
      via: "Detects parent forceVersion change, updates own collapsed state, cascades to children"
      pattern: "onWillUpdateProps"
    - from: "json_tree.xml child JsonTree"
      to: "forceCollapsed and forceVersion props"
      via: "Template passes state.childForceCollapsed and state.childForceVersion as props"
      pattern: "forceCollapsed.*state\\.childForceCollapsed"
---

<objective>
Add Alt/Option+Click recursive expand/collapse to the JsonTree widget.

Purpose: When viewing deeply nested JSON data in the AI Debugger detail panels, users need a way to expand or collapse an entire subtree at once. Alt/Option+clicking a node should recursively toggle all descendants. Normal clicks remain single-node toggles.

Output: Updated json_tree.js and json_tree.xml with Alt+click recursive expand/collapse using the forceCollapsed/forceVersion prop-signaling pattern (same approach proven in quick tasks #3 and #5 at the old file path, now re-implemented in the current component).
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/app/detail/json_tree.js
@ai_debug/static/src/app/detail/json_tree.xml
@.planning/quick/3-ctrl-cmd-click-on-folded-json-tree-node-/3-SUMMARY.md
@.planning/quick/5-fix-broken-ctrl-cmd-click-recursive-expa/5-SUMMARY.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add Alt+click recursive expand/collapse logic to json_tree.js</name>
  <files>ai_debug/static/src/app/detail/json_tree.js</files>
  <action>
Modify `ai_debug/static/src/app/detail/json_tree.js` to add recursive expand/collapse on Alt/Option+click:

1. **Import `onWillUpdateProps`** from `@odoo/owl` (add it alongside `Component` and `useState`).

2. **Add two new optional props** to `static props`:
   - `forceCollapsed: { type: Boolean, optional: true }` — parent signals desired collapsed state
   - `forceVersion: { type: Number, optional: true }` — parent increments to signal a new force event

3. **Expand `state`** in `setup()` to include:
   - `childForceCollapsed: undefined` — what to signal to own children (undefined = no signal)
   - `childForceVersion: 0` — counter incremented to cascade force signals downward

4. **Handle mount-time force** in `setup()`: If `this.props.forceCollapsed` is a boolean (not undefined), use it as the initial `expanded` state (`expanded: forceCollapsed === true ? false : true` — note: `forceCollapsed=false` means force-expand, so `expanded=true`). Also initialize `childForceCollapsed` and `childForceVersion: 1` to propagate the signal to children on mount. Otherwise, keep existing depth-based default (`expanded: this.props.depth < 1`).

5. **Add `onWillUpdateProps(nextProps)`** in `setup()`:
   ```
   onWillUpdateProps(nextProps) {
       if (nextProps.forceVersion !== undefined &&
           nextProps.forceVersion !== this.props.forceVersion) {
           // Parent sent a new force signal
           this.state.expanded = !nextProps.forceCollapsed;
           this.state.childForceCollapsed = nextProps.forceCollapsed;
           this.state.childForceVersion = this.state.childForceVersion + 1;
       }
   }
   ```

6. **Update `toggle(ev)`** to accept the click event and check `ev.altKey`:
   - **Normal click (no Alt):** Toggle `this.state.expanded` as before. Also reset `this.state.childForceCollapsed = undefined` to clear any stale force state from a prior Alt+click.
   - **Alt+click:** Toggle `this.state.expanded`. Then set `this.state.childForceCollapsed` to `!this.state.expanded` (the new collapsed state for children — if we just expanded, children should force-expand, i.e., `forceCollapsed=false`). Increment `this.state.childForceVersion`.

   Wait — be careful with the logic: after toggling, `this.state.expanded` holds the NEW value. If we just expanded (expanded=true), we want children to also expand, so `childForceCollapsed = false`. If we just collapsed (expanded=false), we want children to also collapse, so `childForceCollapsed = true`. So: `this.state.childForceCollapsed = !this.state.expanded`.

The complete toggle method:
```javascript
toggle(ev) {
    this.state.expanded = !this.state.expanded;
    if (ev.altKey) {
        this.state.childForceCollapsed = !this.state.expanded;
        this.state.childForceVersion = this.state.childForceVersion + 1;
    } else {
        this.state.childForceCollapsed = undefined;
    }
}
```
  </action>
  <verify>
Read the modified json_tree.js and confirm:
- `onWillUpdateProps` is imported from `@odoo/owl`
- `forceCollapsed` and `forceVersion` are in `static props`
- `state` includes `childForceCollapsed` and `childForceVersion`
- `setup()` handles mount-time force when `forceCollapsed` is boolean
- `onWillUpdateProps` detects version change and cascades
- `toggle(ev)` checks `ev.altKey` and sets childForce state accordingly
  </verify>
  <done>json_tree.js has full Alt+click recursive expand/collapse logic with mount-aware force propagation and stale-state cleanup on normal clicks</done>
</task>

<task type="auto">
  <name>Task 2: Update json_tree.xml to pass force props to child JsonTree</name>
  <files>ai_debug/static/src/app/detail/json_tree.xml</files>
  <action>
Modify `ai_debug/static/src/app/detail/json_tree.xml`:

1. **Pass force props to child `<JsonTree>` element.** Find the child `<JsonTree>` tag inside the `t-foreach` loop (line ~23) and add two new attributes:
   - `forceCollapsed="state.childForceCollapsed"`
   - `forceVersion="state.childForceVersion"`

   The complete child element should be:
   ```xml
   <JsonTree data="entry[1]"
             label="entry[0]"
             depth="props.depth + 1"
             onExpandText="props.onExpandText"
             forceCollapsed="state.childForceCollapsed"
             forceVersion="state.childForceVersion"/>
   ```

2. **No other template changes needed.** The `t-on-click="toggle"` on the toggle span already passes the native click event, which OWL forwards as the first argument to the handler — so `ev.altKey` will be available.

Verify that the `t-on-click="toggle"` does NOT use `.prevent` or `.stop` modifiers that would consume the event before we read it — it currently does not, so no changes needed there.
  </action>
  <verify>
Read the modified json_tree.xml and confirm:
- The child `<JsonTree>` element has `forceCollapsed="state.childForceCollapsed"` and `forceVersion="state.childForceVersion"` attributes
- The `t-on-click="toggle"` remains unchanged (no modifiers)
- No other unintended changes
  </verify>
  <done>json_tree.xml passes forceCollapsed and forceVersion props to all child JsonTree instances, enabling recursive signal propagation</done>
</task>

</tasks>

<verification>
Manual testing in the AI Debugger:
1. Open the AI Debugger and navigate to a detail panel with nested JSON data (e.g., a tool call with nested arguments).
2. **Normal click** on a collapsed node's toggle arrow: only that node expands. Its children remain in their default state.
3. **Normal click** on an expanded node: only that node collapses.
4. **Alt+click** (Option+click on Mac) on a collapsed node: the node and all descendants recursively expand.
5. **Alt+click** on an expanded node: the node and all descendants recursively collapse.
6. After a recursive expand, **normal click** a single child node: only that child toggles independently (no residual recursive behavior).
7. After a recursive collapse, **Alt+click** to expand again: all descendants expand correctly.
</verification>

<success_criteria>
- Alt/Option+click on any expandable JSON node recursively expands or collapses the entire subtree
- Normal click behavior is completely unchanged (single-node toggle)
- No stale force state leaks between interactions (normal click after recursive clears force state)
- Mount-time force propagation works (freshly mounted children during recursive expand receive the force signal)
</success_criteria>

<output>
After completion, create `.planning/quick/14-add-alt-option-click-recursive-expand-co/14-SUMMARY.md`
</output>
