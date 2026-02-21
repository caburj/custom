/** @odoo-module **/
import { Component, useState } from "@odoo/owl";

const TRUNCATION_THRESHOLD = 300;

export class JsonTree extends Component {
    static template = "ai_debug.JsonTree";
    static components = { JsonTree };  // Self-reference for recursive rendering
    static props = {
        data: true,                    // Any JSON value
        label: { type: String, optional: true },
        depth: { type: Number, optional: true },
        onExpandText: { type: Function, optional: true },  // Callback for long-text popup
    };
    static defaultProps = { depth: 0 };

    setup() {
        this.state = useState({
            expanded: this.props.depth < 1,  // Auto-expand depth 0 only
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

    toggle() {
        this.state.expanded = !this.state.expanded;
    }

    onClickLongString() {
        if (this.props.onExpandText) {
            this.props.onExpandText(this.props.label || "Value", this.props.data);
        }
    }
}
