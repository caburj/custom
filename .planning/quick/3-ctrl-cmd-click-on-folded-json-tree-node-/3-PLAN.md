---
phase: quick
plan: 3
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/debug_panel/json_tree/json_tree.js
  - ai_debug/static/src/debug_panel/json_tree/json_tree.xml
autonomous: true
requirements: [QUICK-3]
must_haves:
  truths:
    - "Ctrl/Cmd+click on a collapsed JSON tree node unfolds it AND all descendants recursively"
    - "Ctrl/Cmd+click on an expanded JSON tree node collapses it AND all descendants recursively"
    - "Normal click (no modifier) still toggles only the clicked node, same as before"
  artifacts:
    - path: "ai_debug/static/src/debug_panel/json_tree/json_tree.js"
      provides: "Recursive toggle logic via forceCollapsed/forceVersion prop propagation"
      contains: "forceVersion"
    - path: "ai_debug/static/src/debug_panel/json_tree/json_tree.xml"
      provides: "Template passes forceCollapsed and forceVersion to child JsonTree"
      contains: "forceCollapsed"
  key_links:
    - from: "json_tree.js toggle()"
      to: "state.childForceVersion"
      via: "ev.ctrlKey || ev.metaKey check increments version"
      pattern: "ctrlKey.*metaKey"
    - from: "json_tree.js onWillUpdateProps"
      to: "state.collapsed"
      via: "Reacts to forceVersion change from parent, sets own collapsed and propagates to children"
      pattern: "onWillUpdateProps"
    - from: "json_tree.xml"
      to: "json_tree.js state.childForceCollapsed"
      via: "Template binds forceCollapsed and forceVersion props on child JsonTree elements"
      pattern: "forceCollapsed"
---

<objective>
Add recursive expand/collapse to the JsonTree component via Ctrl/Cmd+click.

Purpose: When inspecting deeply nested JSON (tool call args, LLM responses), users need a way to quickly unfold or fold entire subtrees instead of clicking each node one by one.

Output: Updated json_tree.js and json_tree.xml with recursive toggle behavior.
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
  <name>Task 1: Add recursive toggle logic to JsonTree JS</name>
  <files>ai_debug/static/src/debug_panel/json_tree/json_tree.js</files>
  <action>
Update the JsonTree component to support recursive expand/collapse via a forceCollapsed + forceVersion prop-signaling pattern.

1. **Update import:** Add `onWillUpdateProps` to the import from `@odoo/owl`:
   ```js
   import { Component, onWillUpdateProps, useState } from "@odoo/owl";
   ```

2. **Add new props** to `static props`:
   ```js
   forceCollapsed: { type: Boolean, optional: true },
   forceVersion: { type: Number, optional: true },
   ```

3. **Expand state** in `setup()` to include child-propagation fields:
   ```js
   setup() {
       const depth = this.props.depth ?? 0;
       const maxDepth = this.props.maxDepth ?? 2;
       this.state = useState({
           collapsed: depth >= maxDepth,
           childForceCollapsed: undefined,
           childForceVersion: 0,
       });
       onWillUpdateProps((nextProps) => {
           if (nextProps.forceVersion !== undefined
               && nextProps.forceVersion !== this.props.forceVersion) {
               this.state.collapsed = nextProps.forceCollapsed;
               // Propagate to own children by bumping child version
               this.state.childForceCollapsed = nextProps.forceCollapsed;
               this.state.childForceVersion++;
           }
       });
   }
   ```
   Key detail: Each node increments its own `childForceVersion` counter rather than passing the parent's version through. This ensures every level sees a version change even if the parent's number is reused.

4. **Update `toggle()` method** to accept the click event and detect Ctrl/Cmd:
   ```js
   toggle(ev) {
       this.state.collapsed = !this.state.collapsed;
       if (ev && (ev.ctrlKey || ev.metaKey)) {
           // Recursive: force all descendants to match this node's new state
           this.state.childForceCollapsed = this.state.collapsed;
           this.state.childForceVersion++;
       }
   }
   ```
   Normal click: only toggles self (existing behavior). Ctrl/Cmd+click: toggles self AND signals all descendants to match.

Do NOT change any other methods (getters, copyToClipboard, etc.). Do NOT change static template or static components.
  </action>
  <verify>
Open the file and confirm:
- `onWillUpdateProps` is imported
- `forceCollapsed` and `forceVersion` are in static props
- `setup()` initializes `childForceCollapsed` and `childForceVersion` in state
- `onWillUpdateProps` callback checks `nextProps.forceVersion` !== `this.props.forceVersion`
- `toggle(ev)` checks `ev.ctrlKey || ev.metaKey`
- No syntax errors: run `node -e "require('fs').readFileSync('ai_debug/static/src/debug_panel/json_tree/json_tree.js', 'utf8')"` to confirm file is readable
  </verify>
  <done>JsonTree JS has recursive toggle logic: Ctrl/Cmd+click propagates collapse/expand signal to descendants via childForceCollapsed/childForceVersion state, and onWillUpdateProps reacts to parent signals.</done>
</task>

<task type="auto">
  <name>Task 2: Update JsonTree template to pass force props to children</name>
  <files>ai_debug/static/src/debug_panel/json_tree/json_tree.xml</files>
  <action>
Update the child `<JsonTree>` element in the template to pass the recursive toggle props.

Find the existing child JsonTree tag (around line 50-55):
```xml
<JsonTree
  value="entry[1]"
  label="entry[0]"
  depth="(props.depth ?? 0) + 1"
  maxDepth="props.maxDepth ?? 2"
/>
```

Add `forceCollapsed` and `forceVersion` attributes so it becomes:
```xml
<JsonTree
  value="entry[1]"
  label="entry[0]"
  depth="(props.depth ?? 0) + 1"
  maxDepth="props.maxDepth ?? 2"
  forceCollapsed="state.childForceCollapsed"
  forceVersion="state.childForceVersion"
/>
```

No other template changes needed. The `t-on-click.stop="toggle"` on the button already passes the native MouseEvent to the toggle method (OWL passes the event as the first argument to inline handler references).
  </action>
  <verify>
Open the file and confirm the child `<JsonTree>` element has both `forceCollapsed="state.childForceCollapsed"` and `forceVersion="state.childForceVersion"` attributes. Confirm no other template changes were made.
  </verify>
  <done>Template passes forceCollapsed and forceVersion from parent state to all child JsonTree instances, completing the recursive propagation chain.</done>
</task>

</tasks>

<verification>
1. Open the AI Debugger panel in Odoo with a debug trace that has nested JSON data (e.g., a tool call with nested args).
2. Normal click on a collapsed node: only that node expands. Normal click on expanded node: only that node collapses. (Existing behavior preserved.)
3. Ctrl+click (or Cmd+click on Mac) on a collapsed node: that node AND all descendants expand recursively.
4. Ctrl+click (or Cmd+click on Mac) on an expanded node: that node AND all descendants collapse recursively.
5. After a recursive expand, normal-clicking a single child node still toggles only that child independently.
</verification>

<success_criteria>
- Ctrl/Cmd+click on collapsed node recursively unfolds entire subtree
- Ctrl/Cmd+click on expanded node recursively collapses entire subtree
- Normal click behavior is completely unchanged
- No regressions in JsonTree rendering (scalars, arrays, objects, copy button all work)
</success_criteria>

<output>
After completion, create `.planning/quick/3-ctrl-cmd-click-on-folded-json-tree-node-/3-SUMMARY.md`
</output>
