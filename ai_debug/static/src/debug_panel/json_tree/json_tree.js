/** @odoo-module **/

import { Component, onWillUpdateProps, useState } from "@odoo/owl";

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
        forceCollapsed: { type: Boolean, optional: true },
        forceVersion: { type: Number, optional: true },
    };

    static defaultProps = {
        depth: 0,
        maxDepth: 2,
    };

    setup() {
        const depth = this.props.depth ?? 0;
        const maxDepth = this.props.maxDepth ?? 2;
        const forceActive = typeof this.props.forceCollapsed === "boolean";
        this.state = useState({
            collapsed: forceActive ? this.props.forceCollapsed : depth >= maxDepth,
            childForceCollapsed: forceActive ? this.props.forceCollapsed : undefined,
            childForceVersion: forceActive ? 1 : 0,
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

    async copyToClipboard() {
        try {
            await navigator.clipboard.writeText(JSON.stringify(this.props.value, null, 2));
        } catch {
            // Clipboard API may fail in non-secure contexts; silently ignore.
        }
    }
}
