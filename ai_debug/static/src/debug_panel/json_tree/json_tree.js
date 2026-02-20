/** @odoo-module **/

import { Component, useState } from "@odoo/owl";

/**
 * JsonTree — Recursive collapsible JSON tree renderer.
 *
 * Renders any JSON value (object, array, string, number, boolean, null) as an
 * interactive, syntax-highlighted tree with expand/collapse at each level.
 * Auto-collapses nodes at depth >= maxDepth (default 2).
 *
 * Locked decisions:
 *   - No search/filter functionality
 *   - Syntax colours: string=green, number=blue, boolean=orange, null=gray, key=purple
 *   - Copy-to-clipboard icon visible on hover for object/array nodes only
 */
export class JsonTree extends Component {
    static template = "ai_debug.JsonTree";

    // Self-referential for recursive rendering of child nodes.
    static components = { JsonTree };

    static props = {
        value: { type: true },
        depth: { type: Number, optional: true },
        maxDepth: { type: Number, optional: true },
        label: { type: String, optional: true },
    };

    static defaultProps = {
        depth: 0,
        maxDepth: 2,
    };

    setup() {
        const depth = this.props.depth ?? 0;
        const maxDepth = this.props.maxDepth ?? 2;
        this.state = useState({ collapsed: depth >= maxDepth });
    }

    get isObject() {
        return this.props.value !== null && typeof this.props.value === "object" && !Array.isArray(this.props.value);
    }

    get isArray() {
        return Array.isArray(this.props.value);
    }

    get isComplex() {
        return this.isObject || this.isArray;
    }

    get entries() {
        if (this.isArray) {
            return this.props.value.map((v, i) => [String(i), v]);
        }
        if (this.isObject) {
            return Object.entries(this.props.value);
        }
        return [];
    }

    get childCount() {
        return this.entries.length;
    }

    get bracketOpen() {
        return this.isArray ? "[" : "{";
    }

    get bracketClose() {
        return this.isArray ? "]" : "}";
    }

    get childSummary() {
        const count = this.childCount;
        if (this.isArray) {
            return `${count} ${count === 1 ? "item" : "items"}`;
        }
        return `${count} ${count === 1 ? "key" : "keys"}`;
    }

    get valueType() {
        const v = this.props.value;
        if (v === null) return "null";
        if (typeof v === "boolean") return "boolean";
        if (typeof v === "number") return "number";
        return "string";
    }

    get scalarDisplay() {
        const v = this.props.value;
        if (v === null) return "null";
        if (typeof v === "string") return JSON.stringify(v);
        return String(v);
    }

    toggle() {
        this.state.collapsed = !this.state.collapsed;
    }

    async copyToClipboard() {
        try {
            await navigator.clipboard.writeText(JSON.stringify(this.props.value, null, 2));
        } catch {
            // Clipboard API may fail in non-secure contexts; silently ignore.
        }
    }
}
