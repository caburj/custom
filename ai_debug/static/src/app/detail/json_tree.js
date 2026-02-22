/** @odoo-module **/
import { Component, onWillUpdateProps, useState } from "@odoo/owl";

const TRUNCATION_THRESHOLD = 300;

export class JsonTree extends Component {
    static template = "ai_debug.JsonTree";
    static components = { JsonTree };  // Self-reference for recursive rendering
    static props = {
        data: true,                    // Any JSON value
        label: { type: String, optional: true },
        depth: { type: Number, optional: true },
        onExpandText: { type: Function, optional: true },  // Callback for long-text popup
        forceCollapsed: { type: Boolean, optional: true },
        forceVersion: { type: Number, optional: true },
    };
    static defaultProps = { depth: 0 };

    setup() {
        const forceActive = typeof this.props.forceCollapsed === "boolean";
        this.state = useState({
            expanded: forceActive ? !this.props.forceCollapsed : this.props.depth < 1,
            childForceCollapsed: forceActive ? this.props.forceCollapsed : undefined,
            childForceVersion: forceActive ? 1 : 0,
        });

        onWillUpdateProps((nextProps) => {
            if (nextProps.forceVersion !== undefined &&
                nextProps.forceVersion !== this.props.forceVersion) {
                // Parent sent a new force signal
                this.state.expanded = !nextProps.forceCollapsed;
                this.state.childForceCollapsed = nextProps.forceCollapsed;
                this.state.childForceVersion = this.state.childForceVersion + 1;
            }
        });
    }

    get type() {
        if (this.props.data === null || this.props.data === undefined) return "null";
        if (Array.isArray(this.props.data)) return "array";
        return typeof this.props.data;
    }

    get isExpandable() {
        return this.type === "object" || this.type === "array";
    }

    get childCount() {
        if (!this.isExpandable) return 0;
        return Array.isArray(this.props.data)
            ? this.props.data.length
            : Object.keys(this.props.data || {}).length;
    }

    get entries() {
        if (this.type === "array") return this.props.data.map((v, i) => [String(i), v]);
        if (this.type === "object") return Object.entries(this.props.data || {});
        return [];
    }

    get isLongString() {
        return this.type === "string" && this.props.data.length > TRUNCATION_THRESHOLD;
    }

    get displayValue() {
        if (this.type === "string") {
            if (this.isLongString) {
                return JSON.stringify(this.props.data.slice(0, TRUNCATION_THRESHOLD) + "...");
            }
            return JSON.stringify(this.props.data);
        }
        if (this.type === "null") return "null";
        if (this.type === "boolean") return String(this.props.data);
        if (this.type === "number") return String(this.props.data);
        return "";
    }

    get collapsedPreview() {
        if (this.type === "array") return `Array(${this.childCount})`;
        if (this.type === "object") return `{${this.childCount} keys}`;
        return "";
    }

    toggle(ev) {
        this.state.expanded = !this.state.expanded;
        if (ev.altKey) {
            this.state.childForceCollapsed = !this.state.expanded;
            this.state.childForceVersion = this.state.childForceVersion + 1;
        } else {
            this.state.childForceCollapsed = undefined;
        }
    }

    onClickLongString() {
        if (this.props.onExpandText) {
            this.props.onExpandText(this.props.label || "Value", this.props.data);
        }
    }
}
