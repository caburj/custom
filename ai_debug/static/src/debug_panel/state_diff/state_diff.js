/** @odoo-module **/

import { Component, useState } from "@odoo/owl";

/**
 * computeDiff(before, after) — Deep recursive diff of two plain objects.
 *
 * Returns an array of DiffEntry objects:
 *   { key, status: 'added'|'removed'|'changed'|'unchanged', oldVal, newVal, children? }
 *
 * Rules:
 *   - Key only in `after`        → 'added'
 *   - Key only in `before`       → 'removed'
 *   - Both present, JSON equal   → 'unchanged'
 *   - Both are plain objects (non-array) → 'changed' with recursive children
 *   - Otherwise                  → 'changed' with oldVal/newVal (arrays are atomic)
 */
export function computeDiff(before, after) {
    const beforeObj = before && typeof before === "object" && !Array.isArray(before) ? before : {};
    const afterObj = after && typeof after === "object" && !Array.isArray(after) ? after : {};

    const allKeys = new Set([...Object.keys(beforeObj), ...Object.keys(afterObj)]);
    const result = [];

    for (const key of allKeys) {
        const inBefore = Object.prototype.hasOwnProperty.call(beforeObj, key);
        const inAfter = Object.prototype.hasOwnProperty.call(afterObj, key);

        if (!inBefore && inAfter) {
            result.push({ key, status: "added", oldVal: undefined, newVal: afterObj[key] });
        } else if (inBefore && !inAfter) {
            result.push({ key, status: "removed", oldVal: beforeObj[key], newVal: undefined });
        } else {
            const a = beforeObj[key];
            const b = afterObj[key];
            if (JSON.stringify(a) === JSON.stringify(b)) {
                result.push({ key, status: "unchanged", oldVal: a, newVal: b });
            } else if (
                a !== null && b !== null &&
                typeof a === "object" && typeof b === "object" &&
                !Array.isArray(a) && !Array.isArray(b)
            ) {
                // Both plain objects — recurse for child diff.
                result.push({
                    key,
                    status: "changed",
                    oldVal: a,
                    newVal: b,
                    children: computeDiff(a, b),
                });
            } else {
                result.push({ key, status: "changed", oldVal: a, newVal: b });
            }
        }
    }

    return result;
}

/**
 * StateDiff — Side-by-side before/after state diff viewer.
 *
 * Shows changed keys (added/removed/changed) first with highlighting,
 * and collapsed unchanged keys with an expandable summary row.
 */
export class StateDiff extends Component {
    static template = "ai_debug.StateDiff";

    static props = {
        stateBefore: { optional: true },
        stateAfter: { optional: true },
    };

    setup() {
        this.state = useState({ showUnchanged: false });
    }

    get diff() {
        return computeDiff(this.props.stateBefore || {}, this.props.stateAfter || {});
    }

    get changedEntries() {
        return this.diff.filter((e) => e.status !== "unchanged");
    }

    get unchangedEntries() {
        return this.diff.filter((e) => e.status === "unchanged");
    }

    get unchangedCount() {
        return this.unchangedEntries.length;
    }

    toggleUnchanged() {
        this.state.showUnchanged = !this.state.showUnchanged;
    }

    /**
     * Format a value for compact display in the diff table.
     * Objects get a one-liner JSON string; scalars display directly.
     */
    formatVal(val) {
        if (val === undefined) return "";
        if (val === null) return "null";
        if (typeof val === "object") {
            const s = JSON.stringify(val);
            // Truncate very long strings for readability.
            return s.length > 200 ? s.slice(0, 200) + "…" : s;
        }
        return JSON.stringify(val);
    }
}
