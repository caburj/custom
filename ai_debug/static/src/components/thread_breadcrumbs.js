/** @odoo-module **/

import { Component, props, types as t } from "@odoo/owl";

export class ThreadBreadcrumbs extends Component {
    static template = "ai_debug.ThreadBreadcrumbs";
    props = props({
        thread: t.object(),
        onSelect: t.function(),
    });

    /** Ancestor chain from root to current (inclusive), root first. */
    get path() {
        const chain = [];
        let t = this.props.thread;
        // Safety limit in case of accidental cycle (shouldn't happen)
        let depth = 0;
        while (t && depth < 32) {
            chain.unshift(t);
            t = t.parent_thread_id || null;
            depth++;
        }
        return chain;
    }

    displayName(thread) {
        if (thread.parent_thread_id && thread.agent_id?.name) {
            return thread.agent_id.name;
        }
        return thread.name || thread.agent_id?.name || `Session ${thread.session_id || thread.id}`;
    }

    onLinkClick(threadId) {
        this.props.onSelect(threadId);
    }
}
