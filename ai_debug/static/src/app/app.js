/** @odoo-module **/
import { Component, useState, reactive, onMounted, onWillUnmount, onPatched, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { LoopDetail } from "./detail/loop_detail";
import { IterationDetail } from "./detail/iter_detail";
import { ToolCallDetail } from "./detail/tc_detail";

export class AiDebugApp extends Component {
    static template = "ai_debug.App";
    static props = {};
    static components = { LoopDetail, IterationDetail, ToolCallDetail };

    setup() {
        this.busService = useService("bus_service");

        // Trace data store — useState wraps the Map so OWL's render function
        // observes mutations (.set/.delete/.clear) and triggers re-renders.
        // Nested reactive Maps (iterations, toolCalls) inherit the render
        // callback when accessed through this proxy chain.
        this.traces = useState(new Map());

        // Selection and connection state — completely separate from trace data (SIDE-05)
        this.state = useState({
            connectionStatus: "connecting",
            selectedId: null,
            selectedType: null,   // 'trace' | 'iteration' | 'tool_call'
        });

        // Sidebar DOM ref for auto-scroll
        this.sidebarRef = useRef("sidebar");
        this._needsScroll = false;
        this._flashId = null;
        this._lastArrivedId = null;

        // ----------------------------------------------------------------
        // Bus connection lifecycle handler
        // ----------------------------------------------------------------
        this._onWorkerState = ({ detail }) => {
            if (detail === "CONNECTED") {
                this.state.connectionStatus = "connected";
            } else if (detail === "CONNECTING") {
                this.state.connectionStatus = "reconnecting";
            } else {
                this.state.connectionStatus = "disconnected";
            }
        };

        // ----------------------------------------------------------------
        // Bus event handlers — NEVER touch this.state.selectedId (SIDE-05)
        // ----------------------------------------------------------------

        this._onNewTrace = (payload) => {
            const iterations = reactive(new Map());
            this.traces.set(payload.trace_id, {
                trace_id: payload.trace_id,
                agent_name: payload.agent_name || "Unknown Agent",
                model_name: payload.model_name || "",
                status: "running",
                started_at: new Date(),
                ended_at: null,
                duration_ms: null,
                expanded: true,   // new loops start expanded (locked decision)
                iterations,
                // Phase 7: full payload for detail panel
                instructions: payload.instructions || "",
                tools: payload.tools || [],
                state_snapshot: payload.state_snapshot || {},
            });
            this._lastArrivedId = payload.trace_id;
            this._flashId = payload.trace_id;
            this._needsScroll = true;
            // Auto-select first trace when nothing is selected (SESS-03 + CONTEXT.md)
            if (this.state.selectedId === null) {
                this.state.selectedId = payload.trace_id;
                this.state.selectedType = "trace";
            }
            // Auto-select above only fires when selectedId is null — SIDE-05 preserved
        };

        this._onIteration = (payload) => {
            const trace = this.traces.get(payload.trace_id);
            if (!trace) return;
            // Only create if not already present (avoid blowing away existing toolCalls)
            if (!trace.iterations.has(payload.iteration_id)) {
                const toolCalls = reactive(new Map());
                trace.iterations.set(payload.iteration_id, {
                    iteration_id: payload.iteration_id,
                    trace_id: payload.trace_id,
                    iteration_index: payload.iteration_index,
                    has_error: !!payload.error,
                    receivedAt: new Date(),
                    expanded: false,
                    toolCalls,
                    // Phase 7: full payload for detail panel
                    messages_sent: payload.messages_sent || [],
                    raw_response: payload.raw_response || null,
                    is_final: payload.is_final || false,
                    error: payload.error || null,
                });
                this._lastArrivedId = payload.iteration_id;
                this._needsScroll = true;
            }
            // NEVER touch this.state.selectedId here — SIDE-05
        };

        this._onToolCall = (payload) => {
            const trace = this.traces.get(payload.trace_id);
            if (!trace) return;
            const iteration = trace.iterations.get(payload.iteration_id);
            if (!iteration) return;
            iteration.toolCalls.set(payload.tool_call_id, {
                tool_call_id: payload.tool_call_id,
                iteration_id: payload.iteration_id,
                tool_name: payload.tool_name,
                success: payload.success,
                // Phase 7: full payload for detail panel
                args: payload.args || {},
                result: payload.result,
                error: payload.error || null,
                state_before: payload.state_before || {},
                state_after: payload.state_after || {},
                call_id: payload.call_id || null,
            });
            // NEVER touch this.state.selectedId here — SIDE-05
        };

        this._onLoopEnd = (payload) => {
            const trace = this.traces.get(payload.trace_id);
            if (!trace) return;
            trace.status =
                payload.termination_reason === "success"
                    ? "success"
                    : payload.termination_reason === "max_iterations"
                    ? "max_iterations"
                    : "error";
            trace.ended_at = new Date();
            trace.duration_ms = payload.duration_ms;
            // NEVER touch this.state.selectedId here — SIDE-05
        };

        // ----------------------------------------------------------------
        // Bus lifecycle
        // ----------------------------------------------------------------
        onMounted(async () => {
            this.busService.addEventListener(
                "BUS:WORKER_STATE_UPDATED",
                this._onWorkerState,
            );
            this.busService.subscribe("new_trace", this._onNewTrace);
            this.busService.subscribe("iteration", this._onIteration);
            this.busService.subscribe("tool_call", this._onToolCall);
            this.busService.subscribe("loop_end", this._onLoopEnd);
            await this.busService.addChannel("ai_debug");
        });

        onWillUnmount(() => {
            this.busService.removeEventListener(
                "BUS:WORKER_STATE_UPDATED",
                this._onWorkerState,
            );
            this.busService.unsubscribe("new_trace", this._onNewTrace);
            this.busService.unsubscribe("iteration", this._onIteration);
            this.busService.unsubscribe("tool_call", this._onToolCall);
            this.busService.unsubscribe("loop_end", this._onLoopEnd);
            this.busService.deleteChannel("ai_debug");
        });

        // ----------------------------------------------------------------
        // Post-render: auto-scroll to newest item + flash effect
        // ----------------------------------------------------------------
        onPatched(() => {
            if (this._needsScroll && this._lastArrivedId && this.sidebarRef.el) {
                const el = this.sidebarRef.el.querySelector(
                    `[data-node-id="${this._lastArrivedId}"]`,
                );
                if (el) {
                    el.scrollIntoView({ behavior: "smooth", block: "nearest" });
                }
                this._needsScroll = false;
            }
            if (this._flashId && this.sidebarRef.el) {
                const el = this.sidebarRef.el.querySelector(
                    `[data-node-id="${this._flashId}"]`,
                );
                if (el) {
                    el.classList.add("ai-tree-flash");
                    setTimeout(() => el.classList.remove("ai-tree-flash"), 1200);
                }
                this._flashId = null;
            }
        });
    }

    // ----------------------------------------------------------------
    // User interaction methods — ONLY these may write to state.selectedId
    // ----------------------------------------------------------------

    selectItem(id, type) {
        this.state.selectedId = id;
        this.state.selectedType = type;
        // Clicking a loop also expands it (locked decision)
        if (type === "trace") {
            const trace = this.traces.get(id);
            if (trace) trace.expanded = true;
        }
    }

    toggleExpand(idOrTraceId, typeOrIterationId) {
        // Called as toggleExpand(traceId, 'trace') for loops
        // Called as toggleExpand(traceId, iterationId) for iterations
        if (typeOrIterationId === "trace") {
            const trace = this.traces.get(idOrTraceId);
            if (trace) trace.expanded = !trace.expanded;
        } else {
            // Two string args: first is traceId, second is iterationId
            const trace = this.traces.get(idOrTraceId);
            if (!trace) return;
            const iteration = trace.iterations.get(typeOrIterationId);
            if (iteration) iteration.expanded = !iteration.expanded;
        }
    }

    clearAll() {
        this.traces.clear();
        this.state.selectedId = null;
        this.state.selectedType = null;
    }

    // ----------------------------------------------------------------
    // Selected data getters — used by detail panel components
    // ----------------------------------------------------------------

    getSelectedTrace() {
        return this.traces.get(this.state.selectedId) || null;
    }

    getSelectedIteration() {
        for (const trace of this.traces.values()) {
            if (trace.iterations.has(this.state.selectedId)) {
                return trace.iterations.get(this.state.selectedId);
            }
        }
        return null;
    }

    getSelectedToolCall() {
        for (const trace of this.traces.values()) {
            for (const iter of trace.iterations.values()) {
                if (iter.toolCalls.has(this.state.selectedId)) {
                    return iter.toolCalls.get(this.state.selectedId);
                }
            }
        }
        return null;
    }

    // ----------------------------------------------------------------
    // Ancestor getters — used in template for breadcrumb tinting
    // ----------------------------------------------------------------

    get selectedTraceId() {
        const { selectedId, selectedType } = this.state;
        if (!selectedId) return null;
        if (selectedType === "trace") return selectedId;
        if (selectedType === "iteration") {
            for (const [traceId, trace] of this.traces) {
                if (trace.iterations.has(selectedId)) return traceId;
            }
        }
        if (selectedType === "tool_call") {
            for (const [traceId, trace] of this.traces) {
                for (const [, iter] of trace.iterations) {
                    if (iter.toolCalls.has(selectedId)) return traceId;
                }
            }
        }
        return null;
    }

    get selectedIterationId() {
        const { selectedId, selectedType } = this.state;
        if (!selectedId) return null;
        if (selectedType === "iteration") return selectedId;
        if (selectedType === "tool_call") {
            for (const [, trace] of this.traces) {
                for (const [iterId, iter] of trace.iterations) {
                    if (iter.toolCalls.has(selectedId)) return iterId;
                }
            }
        }
        return null;
    }

    // ----------------------------------------------------------------
    // Iteration duration helpers
    // ----------------------------------------------------------------

    getIterationDuration(trace, iterationId) {
        const iterationKeys = [...trace.iterations.keys()];
        const idx = iterationKeys.indexOf(iterationId);
        const iteration = trace.iterations.get(iterationId);
        if (!iteration) return null;

        // Find next iteration (in insertion order) to compute delta
        const nextKey = iterationKeys[idx + 1];
        if (nextKey) {
            const nextIteration = trace.iterations.get(nextKey);
            const delta = nextIteration.receivedAt - iteration.receivedAt;
            return this._formatDuration(delta);
        }

        // Last iteration: if loop is complete, use loop end time
        if (trace.ended_at) {
            const delta = trace.ended_at - iteration.receivedAt;
            return this._formatDuration(delta);
        }

        // Still running — no duration yet
        return null;
    }

    _formatDuration(ms) {
        if (ms < 1000) return `${Math.round(ms)}ms`;
        if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
        const mins = Math.floor(ms / 60000);
        const secs = Math.round((ms % 60000) / 1000);
        return `${mins}m ${secs}s`;
    }

    // ----------------------------------------------------------------
    // Status display helpers
    // ----------------------------------------------------------------

    get statusColor() {
        return this.state.connectionStatus === "connected"
            ? "connected"
            : "disconnected";
    }

    get statusLabel() {
        switch (this.state.connectionStatus) {
            case "connected":
                return "Connected";
            case "reconnecting":
                return "Reconnecting...";
            case "disconnected":
                return "Disconnected";
            default:
                return "Connecting...";
        }
    }
}
