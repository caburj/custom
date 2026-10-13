/** @odoo-module **/
import { Component, computed, proxy, t, useProps } from "@odoo/owl";
import { Notebook } from "@web/core/notebook/notebook";
import { CopyButton } from "@web/core/copy_button/copy_button";
import { useService } from "@web/core/utils/hooks";
import { JsonTree } from "./json_tree";
import { TextPopupDialog } from "./text_popup";
import { formatCount, formatCredits, formatDuration, getTraceTotals } from "../format_metrics";
import { parentTool } from "../trace_store";
import { extractRagContexts } from "../event_payload";

export class LoopDetail extends Component {
    static template = "ai_debug.LoopDetail";
    static components = { Notebook, CopyButton, JsonTree };
    props = useProps({
        trace: t.object().optional(),
        traceFamily: t.array(t.object()),
    });

    setup() {
        try {
            this.dialog = useService("dialog");
        } catch {
            this.dialog = null;
        }
        this.formatDuration = formatDuration;
        this.formatCount = formatCount;
        this.formatCredits = formatCredits;
        this.getTraceTotals = getTraceTotals;
        this.usageState = proxy({ mode: "initial", expanded: new Map() });
        this.usageTree = computed(() => this.buildUsageTree());
        this.usageRows = computed(() => {
            const rows = [];
            const collect = (node, depth) => {
                const expanded =
                    this.usageState.expanded.get(node.id) ??
                    (this.usageState.mode === "expanded" ||
                        (this.usageState.mode === "initial" &&
                            (depth === 0 || node.type === "iteration")));
                rows.push({ ...node, depth, expanded });
                if (expanded) {
                    for (const child of node.children) {
                        collect(child, depth + 1);
                    }
                }
            };
            collect(this.usageTree(), 0);
            return rows;
        });
    }

    buildUsageTree() {
        const traces = new Map(this.props.traceFamily.map((trace) => [trace.trace_id, trace]));
        const agents = new Map(
            this.props.traceFamily.map((trace) => [
                trace.trace_id,
                {
                    id: trace.trace_id,
                    type: "agent",
                    trace,
                    label: trace.trace_label || trace.agent_name,
                    query: trace.user_query,
                    children: [...trace.iterations.values()]
                        .sort((a, b) => a.iteration_index - b.iteration_index)
                        .map((iteration) => ({
                            id: `${trace.trace_id}:${iteration.iteration_id}`,
                            type: "iteration",
                            iteration,
                            tokens: iteration.tokens,
                            cost: iteration.cost,
                            duration_ms: iteration.duration_ms,
                            children: [],
                        })),
                },
            ])
        );
        for (const trace of this.props.traceFamily) {
            if (trace === this.props.trace) {
                continue;
            }
            const parent = agents.get(trace.parent_trace_id);
            const requestId =
                parentTool(traces, trace)?.iteration.iteration_id ?? trace.parent_request_uuid;
            const round = parent.children.find(
                (node) => node.type === "iteration" && node.iteration.iteration_id === requestId
            );
            const agent = agents.get(trace.trace_id);
            (round || parent).children.push(agent);
        }
        const populateTotals = (node) => {
            const family = node.type === "agent" ? [node.trace] : [];
            for (const child of node.children) {
                family.push(...populateTotals(child));
            }
            const totals = getTraceTotals(family);
            if (node.type === "agent") {
                node.tokens = totals.has_token_metrics
                    ? {
                          input: totals.total_input,
                          cache_read: totals.total_cached,
                          output: totals.total_output,
                      }
                    : null;
                node.cost = totals.cost_count ? totals.total_cost : null;
                node.duration_ms = totals.has_duration_metrics ? totals.total_duration_ms : null;
            } else {
                node.subagentCost = totals.cost_count ? totals.total_cost : null;
            }
            node.children = node.children.filter(
                (child) =>
                    child.tokens ||
                    child.cost != null ||
                    child.duration_ms != null ||
                    child.children.length
            );
            return family;
        };
        const root = agents.get(this.props.trace.trace_id);
        populateTotals(root);
        return root;
    }

    /** @param {{ id: string, expanded: boolean }} row */
    toggleUsageRow(row) {
        this.usageState.expanded.set(row.id, !row.expanded);
    }

    /** @param {"expanded" | "collapsed"} mode */
    setUsageExpansion(mode) {
        this.usageState.mode = mode;
        this.usageState.expanded.clear();
    }

    openTextPopup(title, content, language) {
        if (!this.dialog) return;
        this.dialog.add(TextPopupDialog, { title, content, language: language || "markdown" });
    }

    get ragContexts() {
        const firstIter = [...this.props.trace.iterations.values()][0];
        if (!firstIter || !firstIter.messages_sent) return null;
        return extractRagContexts(firstIter.messages_sent);
    }

    get instructionsContent() {
        return this.props.trace.instructions || "";
    }
}
