/** @odoo-module **/

import { Component, plugin, proxy, useEffect, props, types as t } from "@odoo/owl";
import { ToolCallCard } from "@ai_debug/components/tool_call_card";
import { JsonViewer } from "@ai_debug/components/json_viewer";
import { reconstructMessagesSent } from "@ai_debug/components/messages_reconstruction";
import { StatusBadge } from "@ai_debug/components/status_badge";
import { AvailableToolCard } from "@ai_debug/components/available_tool_card";
import { TextBlock } from "@ai_debug/components/text_block";
import { formatDuration, formatTokens } from "@ai_debug/components/format";
import { AiDebugStore } from "@ai_debug/store";

export class IterationSection extends Component {
    static template = "ai_debug.IterationSection";
    static components = { ToolCallCard, JsonViewer, StatusBadge, AvailableToolCard, TextBlock };
    props = props({
        iteration: t.object(),
        total: t.number(),
        isLoopRunning: t.boolean().optional(),
    });

    store = plugin(AiDebugStore);

    setup() {
        this.state = proxy({
            expanded: false,
            activeTab: "tools",
        });

        // Auto-expand + switch to "Tool Calls" tab when a focus request targets
        // a tool call inside this iteration. Tool-call cards only render under
        // that tab, so the cards downstream effect would no-op without it.
        useEffect(() => {
            const tcId = this.store.focusToolCallId();
            // touch focusNonce so a repeated focus on the same id re-fires
            this.store.focusNonce();
            if (tcId == null) return;
            const tc = this.store.get("ai.debug.tool.call", tcId);
            if (tc?.iteration_id?.id !== this.props.iteration.id) return;
            if (!this.state.expanded) this.state.expanded = true;
            if (this.state.activeTab !== "tools") this.state.activeTab = "tools";
        });

        // Lazy-load the available_tool_ids batch only when the user actually
        // opens the "Available Tools" tab. Records stay cached for the
        // session so repeat opens are free.
        useEffect(() => {
            if (this.state.activeTab !== "available") return;
            this.store.ensureLazyField(
                this.props.iteration, "available_tool_ids",
            );
        });
    }

    toggleExpanded(ev) {
        this.state.expanded = !this.state.expanded;
        ev.currentTarget.dispatchEvent(new Event("user-toggle", { bubbles: true }));
    }

    get summary() {
        const tc = this.props.iteration.tool_call_ids;
        if (tc && tc.length > 0) {
            return tc.map((t) => t.name).join(", ");
        }
        if (this.props.iteration.output_message) {
            const msg = this.props.iteration.output_message;
            return msg.length > 80 ? msg.slice(0, 80) + "…" : msg;
        }
        return "LLM call";
    }

    get isFinal() {
        return this.props.iteration.sequence === this.props.total && !this.props.isLoopRunning;
    }

    get isRefused() {
        // Subtle accent on the issuing iteration when any of its tool calls was
        // refused (data-driven via ai.debug.tool.call.refused), so the iteration
        // that fired the declined/folded call reads as such at a glance.
        const tcs = this.props.iteration.tool_call_ids;
        return Boolean(tcs && tcs.some((tc) => tc.refused));
    }

    setTab(tab) {
        this.state.activeTab = tab;
    }

    get messagesSent() {
        // Prefer the stored messages_sent; fall back to client-side delta
        // reconstruction for rows / v1 imported bundles that predate it.
        // A NULL jsonb column surfaces over search_read as `false`, NOT
        // null/undefined — test for a real array, not `!= null`, or a NULL
        // row would render literal `false`.
        const stored = this.props.iteration.messages_sent;
        if (Array.isArray(stored)) {
            return stored;
        }
        return reconstructMessagesSent(this.props.iteration);
    }

    formatDuration(ms) {
        return formatDuration(ms);
    }

    formatTokens(n) {
        return formatTokens(n);
    }
}
