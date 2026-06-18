/** @odoo-module **/

import { Component, plugin, proxy, signal, useEffect, props, types as t } from "@odoo/owl";
import { IterationSection } from "@ai_debug/components/iteration_section";
import { ErrorBanner } from "@ai_debug/components/error_banner";
import { StatusBadge } from "@ai_debug/components/status_badge";
import { formatDuration, formatTokens } from "@ai_debug/components/format";
import { AiDebugStore } from "@ai_debug/store";

export class LoopDetailStrip extends Component {
    static template = "ai_debug.LoopDetailStrip";
    static components = { IterationSection, ErrorBanner, StatusBadge };
    props = props({
        loop: t.object(),
        agentName: t.string().optional(),
        modelName: t.string().optional(),
        defaultExpanded: t.boolean().optional(),
    });

    store = plugin(AiDebugStore);

    setup() {
        this.rootRef = signal(null);
        this.state = proxy({
            expanded: this.props.defaultExpanded ?? false,
        });

        // Auto-expand when a focus request targets a tool call inside this loop.
        useEffect(() => {
            const tcId = this.store.focusToolCallId();
            // touch focusNonce so a repeated focus on the same id re-fires
            this.store.focusNonce();
            if (tcId == null) return;
            if (this._containsToolCall(tcId) && !this.state.expanded) {
                this.state.expanded = true;
            }
        });

        // Auto-expand + scroll-into-view when this loop is the focus target
        // (clicked from a parent tool-call's child-loop badge).
        useEffect(() => {
            const target = this.store.focusLoopId();
            // touch focusNonce so a repeated focus on the same id re-fires
            this.store.focusNonce();
            if (target !== this.props.loop.id) return;
            if (!this.state.expanded) this.state.expanded = true;
            this._scrollSelfIntoView();
        });
    }

    _scrollSelfIntoView() {
        // Two RAFs: first lets t-if branches render, second lets layout
        // settle so getBoundingClientRect returns post-expand values. Mirrors
        // the pattern in ToolCallCard._focusSelf.
        requestAnimationFrame(() => requestAnimationFrame(() => {
            const el = this.rootRef();
            if (!el) return;
            const container = el.closest(".conversation-view");
            if (container) {
                const containerRect = container.getBoundingClientRect();
                const elRect = el.getBoundingClientRect();
                const target = container.scrollTop
                    + (elRect.top - containerRect.top)
                    - (containerRect.height / 2)
                    + (elRect.height / 2);
                container.scrollTo({ top: Math.max(0, target), behavior: "smooth" });
            }
            // Release the sentinel-suppression after a beat. No
            // visibility observer here -- the strip is always visible
            // once we expand it, so a fixed delay is enough.
            setTimeout(() => this.store.endFocus(), 600);
        }));
    }

    /** True if `tcId` belongs to one of this loop's iterations. */
    _containsToolCall(tcId) {
        const tc = this.store.get("ai.debug.tool.call", tcId);
        return tc?.iteration_id?.loop_id?.id === this.props.loop.id;
    }

    toggle() {
        this.state.expanded = !this.state.expanded;
        this.rootRef()?.dispatchEvent(new Event("user-toggle", { bubbles: true }));
    }

    get iterationCount() {
        return this.props.loop.iteration_ids?.length || this.props.loop.iteration_count || 0;
    }

    get toolCallCount() {
        const iterations = this.props.loop.iteration_ids || [];
        return iterations.reduce((sum, it) => sum + (it.tool_call_ids?.length || 0), 0);
    }

    formatDuration(ms) {
        return formatDuration(ms);
    }

    formatTokens(n) {
        return formatTokens(n);
    }
}
