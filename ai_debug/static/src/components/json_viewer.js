/** @odoo-module **/
// Ported from ai_debug_deprecated with adaptations.

import { Component, proxy, signal, useEffect, props, types as t } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { CopyButton } from "@web/core/copy_button/copy_button";
import { TextBlock } from "@ai_debug/components/text_block";
import { TextDialog } from "@ai_debug/components/text_dialog";
import { useOverflowDetection } from "@ai_debug/hooks/use_overflow_detection";

class JsonTree extends Component {
    static template = "ai_debug.JsonTree";
    static components = { CopyButton };  // JsonTree self-reference added below
    props = props({
        data: t.any().optional(),
        label: t.string().optional(),
        depth: t.number().optional(),
        forceCollapsed: t.boolean().optional(),
        forceVersion: t.number().optional(),
        expandDepth: t.number().optional(),
    });

    setup() {
        this.dialog = useService("dialog");
        this.stringRef = signal(null);
        this.overflow = useOverflowDetection(this.stringRef);
        const forceActive = typeof this.props.forceCollapsed === "boolean";
        const expandDepth = this.props.expandDepth || 0;
        const depthExpands = expandDepth >= 1;
        this.state = proxy({
            expanded: forceActive ? !this.props.forceCollapsed : depthExpands,
            childForceCollapsed: forceActive ? this.props.forceCollapsed : undefined,
            childForceVersion: forceActive ? 1 : 0,
            childExpandDepth: depthExpands ? expandDepth - 1 : 0,
        });

        // Track the previous forceVersion so we can detect changes in the
        // effect below (OWL 3 replacement for onWillUpdateProps).
        let prevForceVersion = this.props.forceVersion;
        useEffect(() => {
            const cur = this.props.forceVersion;
            if (cur !== undefined && cur !== prevForceVersion) {
                this.state.expanded = !this.props.forceCollapsed;
                this.state.childForceCollapsed = this.props.forceCollapsed;
                this.state.childForceVersion = this.state.childForceVersion + 1;
            }
            prevForceVersion = cur;
        });
    }

    get type() {
        const { data } = this.props;
        if (data === null || data === undefined) return "null";
        if (Array.isArray(data)) return "array";
        return typeof data;
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

    static IMAGE_MAGIC = {
        "iVBORw0KGg": "image/png",
        "/9j/": "image/jpeg",
        "R0lGOD": "image/gif",
        "UklGR": "image/webp",
    };

    get isImageValue() {
        if (this.type !== "string" || typeof this.props.data !== "string") return false;
        if (this.props.data.startsWith("data:image/")) return true;
        if (this.props.data.length > 256) {
            for (const prefix of Object.keys(JsonTree.IMAGE_MAGIC)) {
                if (this.props.data.startsWith(prefix)) return true;
            }
        }
        return false;
    }

    get imageSrc() {
        const { data } = this.props;
        if (data.startsWith("data:")) return data;
        for (const [prefix, mime] of Object.entries(JsonTree.IMAGE_MAGIC)) {
            if (data.startsWith(prefix)) return `data:${mime};base64,${data}`;
        }
        return `data:image/png;base64,${data}`;
    }

    get isStringTruncated() {
        return this.type === "string" && this.overflow();
    }

    get displayValue() {
        const { data } = this.props;
        if (this.type === "string") return JSON.stringify(data);
        if (this.type === "null") return "null";
        return String(data);
    }

    get collapsedPreview() {
        if (this.type === "array") return `Array(${this.childCount})`;
        if (this.type === "object") return `{${this.childCount} keys}`;
        return "";
    }

    get subtreeJson() {
        return JSON.stringify(this.props.data, null, 2);
    }

    onClickStringValue() {
        if (!this.isStringTruncated) return;
        this.dialog.add(TextDialog, {
            title: this.props.label || "Value",
            content: this.props.data,
        });
    }

    toggle(ev) {
        this.state.expanded = !this.state.expanded;
        if (ev.altKey) {
            // Alt+click: force-collapse/expand all children recursively
            this.state.childForceCollapsed = !this.state.expanded;
            this.state.childForceVersion = this.state.childForceVersion + 1;
        } else {
            this.state.childForceCollapsed = undefined;
        }
    }
}
JsonTree.components = { ...JsonTree.components, JsonTree };


export class JsonViewer extends Component {
    static template = "ai_debug.JsonViewer";
    static components = { JsonTree, TextBlock };
    props = props({
        data: t.any().optional(),
        placeholder: t.string().optional(),
        title: t.string().optional(),
        defaultExpanded: t.or([t.boolean(), t.number()]).optional(),
    });

    get title() {
        return this.props.title ?? "Value";
    }

    get expandDepth() {
        const v = this.props.defaultExpanded;
        if (v === true) return Number.MAX_SAFE_INTEGER;
        if (typeof v === "number") return v;
        return 0;
    }

    get parsed() {
        const { data } = this.props;
        if (data == null) return { type: "empty" };
        if (typeof data === "string") {
            const trimmed = data.trim();
            if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
                try {
                    return { type: "json", value: JSON.parse(data) };
                } catch {
                    // not valid JSON — fall through to text
                }
            }
            return { type: "text", value: data };
        }
        // Already an object/array/number/boolean
        return { type: "json", value: data };
    }
}
