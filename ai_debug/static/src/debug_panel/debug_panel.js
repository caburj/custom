/** @odoo-module **/

import {
    Component,
    onMounted,
    onPatched,
    onWillUnmount,
    useState,
    useRef,
} from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { JsonTree } from "./json_tree/json_tree";
import { StateDiff } from "./state_diff/state_diff";

/**
 * DebugPanel — Live real-time view of the AI agentic loop.
 *
 * Registers as an ir.actions.client with tag "ai_debug.debug_panel".
 * Opens at /odoo/ai-debug?trace_id=N.
 *
 * Architecture:
 *   - Reads trace_id from action context or URL query string
 *   - Fetches bus_channel UUID and trace metadata via RPC on mount
 *   - Subscribes to ai_debug channel on bus.bus for real-time events
 *   - Renders a vertical timeline of iterations and tool calls
 *   - Lazily fetches full iteration/tool_call detail on expand
 *   - Auto-scrolls to follow latest event, pauses when user scrolls up
 */
export class DebugPanel extends Component {
    static template = "ai_debug.DebugPanel";
    static components = { JsonTree, StateDiff };
    static props = ["action", "*"];

    setup() {
        this.busService = useService("bus_service");
        this.rpc = useService("rpc");

        this.state = useState({
            iterations: [],
            traceStatus: "waiting",
            traceId: null,
            connectionStatus: "connecting",
            traceInfo: null,  // { llm_model, agent_id, iteration_count, ... }
            errorMsg: null,
        });

        this.scrollRef = useRef("timeline");
        this.userScrolledUp = false;
        this.channel = null;

        // Bind handlers so they can be stored for unsubscribe/removeEventListener.
        this._onIteration = this._onIteration.bind(this);
        this._onToolCall = this._onToolCall.bind(this);
        this._onTraceUpdate = this._onTraceUpdate.bind(this);
        this._onWorkerState = this._onWorkerState.bind(this);
        this._onScroll = this._onScroll.bind(this);

        onMounted(async () => {
            await this._init();
        });

        onPatched(() => {
            if (!this.userScrolledUp && this.scrollRef.el) {
                this.scrollRef.el.scrollTop = this.scrollRef.el.scrollHeight;
            }
        });

        onWillUnmount(() => {
            this._teardown();
        });
    }

    // -------------------------------------------------------------------------
    // Init / teardown
    // -------------------------------------------------------------------------

    async _init() {
        // Resolve trace_id: action context first, then URL query string.
        let traceId = this.props.action?.context?.trace_id;
        if (!traceId) {
            const params = new URLSearchParams(window.location.search);
            traceId = params.get("trace_id");
        }

        if (traceId) {
            this.state.traceId = parseInt(traceId, 10);
        }

        if (!this.state.traceId) {
            this.state.errorMsg = "No trace_id provided in URL or action context.";
            this.state.connectionStatus = "disconnected";
            return;
        }

        // Fetch trace metadata and bus channel.
        try {
            const [traceRecord] = await this.rpc("/web/dataset/call_kw", {
                model: "ai.debug.trace",
                method: "read",
                args: [
                    [this.state.traceId],
                    ["bus_channel", "state", "llm_model", "agent_id", "iteration_count"],
                ],
                kwargs: {},
            });

            if (!traceRecord) {
                this.state.errorMsg = `Trace #${this.state.traceId} not found.`;
                this.state.connectionStatus = "disconnected";
                return;
            }

            this.channel = traceRecord.bus_channel;
            this.state.traceInfo = traceRecord;
            // If trace is already complete, reflect that immediately.
            if (traceRecord.state && traceRecord.state !== "running") {
                this.state.traceStatus = traceRecord.state;
            }
        } catch (err) {
            this.state.errorMsg = `Failed to load trace: ${err.message || err}`;
            this.state.connectionStatus = "disconnected";
            return;
        }

        // Subscribe to bus events.
        const fullChannel = `ai_debug:trace:${this.channel}`;
        await this.busService.addChannel(fullChannel);
        this.busService.subscribe("ai_debug/iteration", this._onIteration);
        this.busService.subscribe("ai_debug/tool_call", this._onToolCall);
        this.busService.subscribe("ai_debug/trace_update", this._onTraceUpdate);
        this.busService.addEventListener("BUS:WORKER_STATE_UPDATED", this._onWorkerState);

        // Add scroll tracking.
        if (this.scrollRef.el) {
            this.scrollRef.el.addEventListener("scroll", this._onScroll);
        }

        // Set initial connection status from current bus worker state.
        this._syncConnectionStatus(this.busService.workerState);
    }

    _teardown() {
        if (this.channel) {
            this.busService.unsubscribe("ai_debug/iteration", this._onIteration);
            this.busService.unsubscribe("ai_debug/tool_call", this._onToolCall);
            this.busService.unsubscribe("ai_debug/trace_update", this._onTraceUpdate);
            this.busService.deleteChannel(`ai_debug:trace:${this.channel}`);
        }
        this.busService.removeEventListener("BUS:WORKER_STATE_UPDATED", this._onWorkerState);

        if (this.scrollRef.el) {
            this.scrollRef.el.removeEventListener("scroll", this._onScroll);
        }
    }

    // -------------------------------------------------------------------------
    // Connection status
    // -------------------------------------------------------------------------

    _syncConnectionStatus(workerState) {
        if (workerState === "CONNECTED") {
            this.state.connectionStatus = "connected";
        } else if (workerState === "CONNECTING") {
            this.state.connectionStatus = "reconnecting";
        } else if (workerState === "DISCONNECTED" || workerState === "IDLE") {
            this.state.connectionStatus = "disconnected";
        } else {
            this.state.connectionStatus = "connecting";
        }
    }

    // -------------------------------------------------------------------------
    // Bus event handlers
    // -------------------------------------------------------------------------

    _onIteration(payload) {
        this.state.iterations.push({
            id: payload.iteration_id,
            index: payload.index,
            duration_ms: payload.duration_ms,
            tool_call_count: payload.tool_call_count ?? 0,
            toolCalls: [],
            expanded: false,
            loading: false,
            detail: null,
            activeTab: "messages",
        });
        this.state.traceStatus = "running";
    }

    _onToolCall(payload) {
        const iteration = this.state.iterations.find((it) => it.id === payload.iteration_id);
        if (iteration) {
            iteration.toolCalls.push({
                id: payload.tool_call_id,
                name: payload.tool_name,
                duration_ms: payload.duration_ms,
                success: payload.success,
                expanded: false,
                loading: false,
                detail: null,
            });
            iteration.tool_call_count = iteration.toolCalls.length;
        }
    }

    _onTraceUpdate(payload) {
        if (payload.state) {
            this.state.traceStatus = payload.state;
        }
        if (this.state.traceInfo) {
            if (payload.iteration_count !== undefined) {
                this.state.traceInfo.iteration_count = payload.iteration_count;
            }
        }
    }

    _onWorkerState({ detail }) {
        this._syncConnectionStatus(detail);
    }

    // -------------------------------------------------------------------------
    // Scroll tracking
    // -------------------------------------------------------------------------

    _onScroll() {
        const el = this.scrollRef.el;
        if (!el) return;
        // Near bottom = within 50px of the bottom edge.
        this.userScrolledUp = el.scrollTop + el.clientHeight < el.scrollHeight - 50;
    }

    // -------------------------------------------------------------------------
    // Expand/collapse with lazy detail fetch
    // -------------------------------------------------------------------------

    async toggleIteration(iterationIdx) {
        const iteration = this.state.iterations[iterationIdx];
        if (!iteration) return;

        iteration.expanded = !iteration.expanded;

        if (iteration.expanded && iteration.detail === null && !iteration.loading) {
            iteration.loading = true;
            try {
                const [detail] = await this.rpc("/web/dataset/call_kw", {
                    model: "ai.debug.iteration",
                    method: "read",
                    args: [
                        [iteration.id],
                        ["messages_sent", "raw_response", "state_before", "state_after", "final_message"],
                    ],
                    kwargs: {},
                });
                iteration.detail = detail || null;
            } catch (err) {
                iteration.detail = { _error: `Failed to load: ${err.message || err}` };
            } finally {
                iteration.loading = false;
            }
        }
    }

    async toggleToolCall(iterationIdx, toolCallIdx) {
        const iteration = this.state.iterations[iterationIdx];
        if (!iteration) return;
        const toolCall = iteration.toolCalls[toolCallIdx];
        if (!toolCall) return;

        toolCall.expanded = !toolCall.expanded;

        if (toolCall.expanded && toolCall.detail === null && !toolCall.loading) {
            toolCall.loading = true;
            try {
                const [detail] = await this.rpc("/web/dataset/call_kw", {
                    model: "ai.debug.tool.call",
                    method: "read",
                    args: [
                        [toolCall.id],
                        ["args", "result", "state_before", "state_after", "confirmation_message", "triggered_confirmation", "success"],
                    ],
                    kwargs: {},
                });
                toolCall.detail = detail || null;
            } catch (err) {
                toolCall.detail = { _error: `Failed to load: ${err.message || err}` };
            } finally {
                toolCall.loading = false;
            }
        }
    }

    setActiveTab(iterationIdx, tabName) {
        const iteration = this.state.iterations[iterationIdx];
        if (iteration) {
            iteration.activeTab = tabName;
        }
    }

    // -------------------------------------------------------------------------
    // Display helpers
    // -------------------------------------------------------------------------

    get connectionLabel() {
        return {
            connected: "Connected",
            reconnecting: "Reconnecting",
            disconnected: "Disconnected",
            connecting: "Connecting",
        }[this.state.connectionStatus] ?? "Unknown";
    }

    get traceStatusLabel() {
        return {
            waiting: "Waiting",
            running: "Running",
            done: "Done",
            error: "Error",
            paused: "Paused",
        }[this.state.traceStatus] ?? this.state.traceStatus;
    }

    formatDuration(ms) {
        if (!ms && ms !== 0) return "";
        if (ms < 1000) return `${ms}ms`;
        return `${(ms / 1000).toFixed(1)}s`;
    }

    get isActivelyRunning() {
        return this.state.traceStatus === "running" || this.state.traceStatus === "waiting";
    }
}

registry.category("actions").add("ai_debug.debug_panel", DebugPanel);
