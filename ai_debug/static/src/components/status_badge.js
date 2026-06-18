/** @odoo-module **/

import { Component, props, types as t } from "@odoo/owl";

export class StatusBadge extends Component {
    static template = "ai_debug.StatusBadge";

    props = props({
        status: t.string().optional(), // "success" | "error" | "running" | "max_iterations" | "confirmation" | "refused" | "superseded" | "cancelled"
        isRunning: t.boolean().optional(),
        label: t.string().optional(), // override displayed text
    });

    get displayLabel() {
        if (this.props.label) return this.props.label;
        if (this.props.isRunning) return "running";
        return this.props.status || "unknown";
    }

    get cssClass() {
        if (this.props.isRunning) return "running";
        return this.props.status || "";
    }
}
