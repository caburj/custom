/** @odoo-module **/
import { Component, onWillUpdateProps, useRef, useState } from "@odoo/owl";
import { CopyButton } from "@web/core/copy_button/copy_button";

const TRUNCATION_THRESHOLD = 300;

export class JsonTree extends Component {
    static template = "ai_debug.JsonTree";
    static components = { JsonTree, CopyButton };  // Self-reference for recursive rendering
    static props = {
        data: { optional: true },       // Any JSON value (may be undefined before data arrives)
        label: { type: String, optional: true },
        depth: { type: Number, optional: true },
        onExpandText: { type: Function, optional: true },  // Callback for long-text popup
        onExpandImage: { type: Function, optional: true },  // Callback for image popup
        forceCollapsed: { type: Boolean, optional: true },
        forceVersion: { type: Number, optional: true },
    };
    static defaultProps = { depth: 0 };

    setup() {
        this.imageOverlayRef = useRef("imageOverlay");
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

    /**
     * Base64 magic-byte prefixes for common image formats.
     * Used to detect raw base64 image strings (without a data URI prefix).
     */
    static IMAGE_MAGIC = {
        "iVBORw0KGg": "image/png",  // PNG (\x89PNG...)
        "/9j/":       "image/jpeg", // JPEG (\xff\xd8\xff)
        "R0lGOD":     "image/gif",  // GIF (GIF87a / GIF89a)
        "UklGR":      "image/webp", // WebP (RIFF...WEBP)
    };

    get isImageValue() {
        if (this.type !== "string" || typeof this.props.data !== "string") return false;
        if (this.props.data.startsWith("data:image/")) return true;
        // Detect raw base64 images by magic bytes (must be long enough to be actual image data)
        if (this.props.data.length > 256) {
            for (const prefix of Object.keys(JsonTree.IMAGE_MAGIC)) {
                if (this.props.data.startsWith(prefix)) return true;
            }
        }
        return false;
    }

    get imageSrc() {
        if (this.props.data.startsWith("data:")) return this.props.data;
        // Raw base64 — infer mimetype from magic bytes and build data URI
        for (const [prefix, mime] of Object.entries(JsonTree.IMAGE_MAGIC)) {
            if (this.props.data.startsWith(prefix)) {
                return `data:${mime};base64,${this.props.data}`;
            }
        }
        return `data:image/png;base64,${this.props.data}`;
    }

    get isLongString() {
        return this.type === "string" && !this.isImageValue && this.props.data.length > TRUNCATION_THRESHOLD;
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

    get subtreeJson() {
        return JSON.stringify(this.props.data, null, 2);
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

    onImageMouseEnter(ev) {
        const overlay = this.imageOverlayRef.el;
        if (!overlay) return;
        const rect = ev.currentTarget.getBoundingClientRect();
        // Position below the leaf, aligned to left edge
        overlay.style.top = `${rect.bottom + 6}px`;
        overlay.style.left = `${rect.left}px`;
    }

    onClickImage() {
        if (this.props.onExpandImage) {
            this.props.onExpandImage(this.props.label || "Image", this.imageSrc);
        }
    }
}
