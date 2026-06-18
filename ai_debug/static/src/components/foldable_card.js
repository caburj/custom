/** @odoo-module **/

import { Component, proxy, signal, props, types as t } from "@odoo/owl";

/**
 * Generic collapsible card primitive.
 *
 * Slots:
 *  - ``header`` (required): contents of the clickable row.
 *  - default: body contents, only rendered when expanded.
 *
 * Visually mirrors ``.tool-call`` / ``.tool-call-header`` / ``.tool-call-body``
 * (see app.css). On toggle, bubbles a ``user-toggle`` DOM event so any
 * interested ancestor (e.g. a focus-tracking parent) can react.
 */
export class FoldableCard extends Component {
    static template = "ai_debug.FoldableCard";
    props = props({
        defaultExpanded: t.boolean().optional(),
        slots: t.object({
            header: t.object(),
            default: t.object().optional(),
        }),
    });

    setup() {
        this.rootRef = signal(null);
        this.state = proxy({
            expanded: this.props.defaultExpanded ?? false,
        });
    }

    toggle() {
        this.state.expanded = !this.state.expanded;
        this.rootRef()?.dispatchEvent(new Event("user-toggle", { bubbles: true }));
    }
}
