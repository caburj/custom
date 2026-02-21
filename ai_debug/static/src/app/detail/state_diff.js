/** @odoo-module **/
import { Component } from "@odoo/owl";

export class StateDiff extends Component {
    static template = "ai_debug.StateDiff";
    static props = {
        before: { type: Object, optional: true },
        after: { type: Object, optional: true },
    };

    get hasDiff() {
        return this.props.before && this.props.after;
    }

    get diffRows() {
        const b = this.props.before || {};
        const a = this.props.after || {};
        const allKeys = new Set([...Object.keys(b), ...Object.keys(a)]);
        return [...allKeys].map(key => {
            const bVal = b[key];
            const aVal = a[key];
            if (!(key in b)) return { key, type: "added", before: undefined, after: aVal };
            if (!(key in a)) return { key, type: "removed", before: bVal, after: undefined };
            const changed = JSON.stringify(bVal) !== JSON.stringify(aVal);
            return { key, type: changed ? "changed" : "unchanged", before: bVal, after: aVal };
        });
    }

    get hasChanges() {
        return this.diffRows.some(r => r.type !== "unchanged");
    }

    formatValue(val) {
        if (val === undefined) return "";
        if (val === null) return "null";
        if (typeof val === "object") return JSON.stringify(val, null, 2);
        return String(val);
    }
}
