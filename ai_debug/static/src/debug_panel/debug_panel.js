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
 * Two modes:
 *   1. Direct: /odoo/ai-debug?trace_id=N — shows that specific trace
 *   2. Listen: /odoo/ai-debug (no trace_id) — subscribes to global channel,
 *      auto-attaches to the next new trace that starts
 */
export class DebugPanel extends Component {
    static template = "ai_debug.DebugPanel";
    static components = { JsonTree, StateDiff };
    static props = ["action", "*"];

    setup() {
        this.busService = useService("bus_service");
        this.orm = useService("orm");

        this.state = useState({
            mode: "loading",       // "loading" | "listen" | "trace"
            iterations: [],
            traceStatus: "waiting",
            traceId: null,
            connectionStatus: "connecting",
            traceInfo: null,
            errorMsg: null,
            traceDetailExpanded: false,
            traceDetailLoading: false,
        });

        this.scrollRef = useRef("timeline");
        this.userScrolledUp = false;
        this.channel = null;

        // Bind all handlers once.
        this._onIteration = this._onIteration.bind(this);
        this._onToolCall = this._onToolCall.bind(this);
        this._onTraceUpdate = this._onTraceUpdate.bind(this);
        this._onNewTrace = this._onNewTrace.bind(this);
        this._onWorkerState = this._onWorkerState.bind(this);
        this._onScroll = this._onScroll.bind(this);
        this.toggleIteration = this.toggleIteration.bind(this);
        this.toggleToolCall = this.toggleToolCall.bind(this);
        this.setActiveTab = this.setActiveTab.bind(this);
        this.toggleTraceDetail = this.toggleTraceDetail.bind(this);

        onMounted(async () => {
            // Hide Odoo web client chrome (navbar, chat widget) for standalone feel.
            document.body.classList.add("o_ai_debug_standalone");
            await this._init();
        });

        onPatched(() => {
            if (!this.userScrolledUp && this.scrollRef.el) {
                this.scrollRef.el.scrollTop = this.scrollRef.el.scrollHeight;
            }
        });

        onWillUnmount(() => {
            document.body.classList.remove("o_ai_debug_standalone");
            this._teardown();
        });
    }

    // -------------------------------------------------------------------------
    // Init / teardown
    // -------------------------------------------------------------------------

    async _init() {
        // Subscribe to ALL event types once upfront. The bus service dispatches
        // by notification type regardless of which channel it came from.
        this.busService.subscribe("ai_debug/iteration", this._onIteration);
        this.busService.subscribe("ai_debug/tool_call", this._onToolCall);
        this.busService.subscribe("ai_debug/trace_update", this._onTraceUpdate);
        this.busService.subscribe("ai_debug/new_trace", this._onNewTrace);
        this.busService.addEventListener("BUS:WORKER_STATE_UPDATED", this._onWorkerState);

        if (this.scrollRef.el) {
            this.scrollRef.el.addEventListener("scroll", this._onScroll);
        }

        // Always subscribe to the global traces channel so we can auto-switch
        // to new traces even when viewing a completed one.
        this.busService.addChannel("ai_debug:traces");

        // Resolve trace_id: action context first, then URL query string.
        let traceId = this.props.action?.context?.trace_id;
        if (!traceId) {
            const params = new URLSearchParams(window.location.search);
            traceId = params.get("trace_id");
        }

        if (traceId) {
            await this._loadTrace(parseInt(traceId, 10));
        } else {
            this.state.mode = "listen";
        }

        this._syncConnectionStatus(this.busService.workerState);
    }

    /**
     * Switch to a specific trace channel immediately (synchronous).
     * Used by _onNewTrace to subscribe without any async gap.
     */
    _switchToTraceChannel(traceId, busChannel, traceInfo) {
        // Unsubscribe from previous trace channel.
        if (this.channel) {
            this.busService.deleteChannel(`ai_debug:trace:${this.channel}`);
        }

        this.channel = busChannel;
        this.state.traceId = traceId;
        this.state.mode = "trace";
        this.state.traceStatus = "running";
        this.state.traceInfo = traceInfo;
        this.state.iterations.splice(0);
        this.state.errorMsg = null;
        this.state.traceDetailExpanded = false;
        this.state.traceDetailLoading = false;

        // Subscribe to the trace-specific channel — must happen ASAP.
        this.busService.addChannel(`ai_debug:trace:${busChannel}`);
    }

    /**
     * Load an existing trace by ID (async). For direct-link and history viewing.
     */
    async _loadTrace(traceId) {
        this.state.mode = "trace";
        this.state.traceId = traceId;
        this.state.errorMsg = null;

        try {
            const [traceRecord] = await this.orm.read(
                "ai.debug.trace",
                [traceId],
                ["bus_channel", "state", "llm_model", "agent_id", "iteration_count", "instructions", "rag_context", "tools_definition"],
            );

            if (!traceRecord) {
                this.state.errorMsg = `Trace #${traceId} not found.`;
                return;
            }

            // Unsubscribe from previous trace channel.
            if (this.channel) {
                this.busService.deleteChannel(`ai_debug:trace:${this.channel}`);
            }

            this.channel = traceRecord.bus_channel;
            this.state.traceInfo = traceRecord;
            this.state.traceStatus = traceRecord.state || "waiting";

            // Subscribe to the trace channel (for still-running traces).
            this.busService.addChannel(`ai_debug:trace:${this.channel}`);

            // Load existing iterations.
            this.state.iterations.splice(0);
            await this._loadExistingIterations();
            if (this.state.iterations.length > 0 && this.state.traceStatus === "waiting") {
                this.state.traceStatus = "running";
            }
        } catch (err) {
            this.state.errorMsg = `Failed to load trace: ${err.message || err}`;
        }
    }

    _teardown() {
        this.busService.unsubscribe("ai_debug/iteration", this._onIteration);
        this.busService.unsubscribe("ai_debug/tool_call", this._onToolCall);
        this.busService.unsubscribe("ai_debug/trace_update", this._onTraceUpdate);
        this.busService.unsubscribe("ai_debug/new_trace", this._onNewTrace);
        this.busService.removeEventListener("BUS:WORKER_STATE_UPDATED", this._onWorkerState);

        if (this.channel) {
            this.busService.deleteChannel(`ai_debug:trace:${this.channel}`);
        }
        this.busService.deleteChannel("ai_debug:traces");

        if (this.scrollRef.el) {
            this.scrollRef.el.removeEventListener("scroll", this._onScroll);
        }
    }

    async _loadExistingIterations() {
        try {
            const iterations = await this.orm.searchRead(
                "ai.debug.iteration",
                [["trace_id", "=", this.state.traceId]],
                ["index", "duration_ms", "tool_call_count"],
                { order: "index asc" },
            );
            if (!iterations.length) return;

            const iterationIds = iterations.map((it) => it.id);
            const toolCalls = await this.orm.searchRead(
                "ai.debug.tool.call",
                [["iteration_id", "in", iterationIds]],
                ["iteration_id", "tool_name", "duration_ms", "success"],
                { order: "id asc" },
            );

            const tcByIteration = {};
            for (const tc of toolCalls) {
                const itId = tc.iteration_id[0];
                if (!tcByIteration[itId]) tcByIteration[itId] = [];
                tcByIteration[itId].push({
                    id: tc.id,
                    name: tc.tool_name,
                    duration_ms: tc.duration_ms,
                    success: tc.success,
                    expanded: false,
                    loading: false,
                    detail: null,
                });
            }

            for (const it of iterations) {
                this.state.iterations.push({
                    id: it.id,
                    index: it.index,
                    duration_ms: it.duration_ms,
                    tool_call_count: it.tool_call_count,
                    toolCalls: tcByIteration[it.id] || [],
                    expanded: false,
                    loading: false,
                    detail: null,
                    activeTab: "messages",
                });
            }
        } catch {
            // Non-fatal.
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

    _onNewTrace(payload) {
        // A new trace started — immediately switch to its channel (no async).
        if (!payload.trace_id || !payload.bus_channel) return;
        this._switchToTraceChannel(payload.trace_id, payload.bus_channel, {
            llm_model: payload.llm_model,
            state: payload.state || "running",
        });
    }

    _onIteration(payload) {
        if (payload.trace_id !== this.state.traceId) return;
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
        if (payload.trace_id !== this.state.traceId) return;
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
        if (payload.trace_id !== this.state.traceId) return;
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
        this.userScrolledUp = el.scrollTop + el.clientHeight < el.scrollHeight - 50;
    }

    // -------------------------------------------------------------------------
    // Expand/collapse with lazy detail fetch
    // -------------------------------------------------------------------------

    async toggleTraceDetail() {
        this.state.traceDetailExpanded = !this.state.traceDetailExpanded;
        // Lazy-load if expanding and traceInfo lacks these fields (live mode).
        if (
            this.state.traceDetailExpanded &&
            this.state.traceId &&
            this.state.traceInfo &&
            !("instructions" in this.state.traceInfo) &&
            !this.state.traceDetailLoading
        ) {
            this.state.traceDetailLoading = true;
            try {
                const [detail] = await this.orm.read(
                    "ai.debug.trace",
                    [this.state.traceId],
                    ["instructions", "rag_context", "tools_definition"],
                );
                if (detail) {
                    Object.assign(this.state.traceInfo, detail);
                }
            } catch {
                // Non-fatal — section just shows empty.
            } finally {
                this.state.traceDetailLoading = false;
            }
        }
    }

    async toggleIteration(iterationIdx) {
        const iteration = this.state.iterations[iterationIdx];
        if (!iteration) return;

        iteration.expanded = !iteration.expanded;

        if (iteration.expanded && iteration.detail === null && !iteration.loading) {
            iteration.loading = true;
            try {
                const [detail] = await this.orm.read(
                    "ai.debug.iteration",
                    [iteration.id],
                    ["messages_sent", "raw_response", "state_before", "state_after", "final_message"],
                );
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
                const [detail] = await this.orm.read(
                    "ai.debug.tool.call",
                    [toolCall.id],
                    ["args", "result", "state_before", "state_after", "confirmation_message", "triggered_confirmation", "success"],
                );
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
