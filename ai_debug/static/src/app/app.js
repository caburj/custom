/** @odoo-module **/
import { Component, useState, reactive, onMounted, onWillStart, onWillUnmount, onPatched, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { MainComponentsContainer } from "@web/core/main_components_container";
import { LoopDetail } from "./detail/loop_detail";
import { IterationDetail } from "./detail/iter_detail";
import { ToolCallDetail } from "./detail/tc_detail";
import { probeIDB, writeTrace, deleteTrace, loadAllTraces, serializeTrace } from "./db";
import { ImportPreviewDialog } from "./import_dialog";
import { TextPopupDialog } from "./detail/text_popup";

/**
 * Reconstruct a reactive trace object from a plain IDB-stored record.
 *
 * IDB stores iterations and toolCalls as [id, record] pair arrays (from
 * serializeTrace's .entries() serialization). Dates are ISO strings from
 * the JSON round-trip in writeTrace(). This function reverses both
 * transformations and wraps nested Maps in reactive() so that bus event
 * handlers (.set() calls) trigger OWL re-renders after hydration.
 *
 * hydrated: true is a permanent marker — never removed — used by the
 * template to display the "archived" badge.
 */
function hydrateTrace(plain) {
    const iterations = reactive(new Map());
    for (const [iterId, iter] of plain.iterations ?? []) {
        const toolCalls = reactive(new Map());
        for (const [tcId, tc] of iter.toolCalls ?? []) {
            toolCalls.set(tcId, tc);
        }
        iterations.set(iterId, {
            ...iter,
            receivedAt: iter.receivedAt ? new Date(iter.receivedAt) : null,
            expanded: false,
            toolCalls,
        });
    }
    return {
        ...plain,
        started_at: plain.started_at ? new Date(plain.started_at) : null,
        ended_at: plain.ended_at ? new Date(plain.ended_at) : null,
        created_ts: plain.created_ts || (plain.started_at ? new Date(plain.started_at).getTime() : 0),
        expanded: false,
        hydrated: true,
        iterations,
    };
}

export class AiDebugApp extends Component {
    static template = "ai_debug.App";
    static props = {};
    static components = { LoopDetail, IterationDetail, ToolCallDetail, MainComponentsContainer };

    setup() {
        this.busService = useService("bus_service");

        // Trace data store — useState wraps the Map so OWL's render function
        // observes mutations (.set/.delete/.clear) and triggers re-renders.
        // Nested reactive Maps (iterations, toolCalls) inherit the render
        // callback when accessed through this proxy chain.
        this.traces = useState(new Map());

        // Selection state — completely separate from trace data (SIDE-05)
        this.state = useState({
            selectedId: null,
            selectedType: null,   // 'trace' | 'iteration' | 'tool_call'
            ephemeralMode: false, // true when IDB is unavailable (private browsing or write failure)
            checkedTraceIds: new Set(),  // Phase 11: checkbox selection for bulk delete
            sidebarWidth: 280,
        });

        // Sidebar DOM ref for auto-scroll
        this.sidebarRef = useRef("sidebar");
        // Select-all checkbox DOM ref for indeterminate state sync
        this.selectAllRef = useRef("selectAll");
        // Hidden file input ref for import file picker
        this.fileInputRef = useRef("fileInput");
        try {
            this.dialog = useService("dialog");
        } catch {
            this.dialog = null;
        }
        this._needsScroll = false;
        this._flashId = null;
        this._lastArrivedId = null;
        // Pending-child buffer for out-of-order subagent traces (TREE-05).
        // Keyed by parent_tool_call_id (= LLM call_id). Each entry holds
        // the child trace payload and a 30s promotion timer.
        this._pendingChildren = {};

        // ----------------------------------------------------------------
        // Bus event handlers — NEVER touch this.state.selectedId (SIDE-05)
        // ----------------------------------------------------------------

        this._onNewTrace = (payload) => {
            const { parent_trace_id, parent_tool_call_id } = payload;

            // --- Child trace: check for parent before placing ---
            if (parent_trace_id && parent_tool_call_id) {
                const parentTrace = this.traces.get(parent_trace_id);
                if (parentTrace) {
                    // Parent trace exists — check if the tool call node exists
                    let parentTcFound = false;
                    for (const iter of parentTrace.iterations.values()) {
                        if (iter.toolCalls.has(parent_tool_call_id)) {
                            parentTcFound = true;
                            break;
                        }
                        // Also check by call_id field (tool_call_started uses our UUID as key,
                        // but parent_tool_call_id is the LLM call_id stored in the call_id field)
                        for (const tc of iter.toolCalls.values()) {
                            if (tc.call_id === parent_tool_call_id) {
                                parentTcFound = true;
                                break;
                            }
                        }
                        if (parentTcFound) break;
                    }
                    if (parentTcFound) {
                        // Parent tool call exists — place the child trace immediately
                        this._placeTrace(payload);
                        return;
                    }
                }

                // Parent not found — buffer with 30s timeout
                const timer = setTimeout(() => {
                    // Promote orphan to root — place as a root trace but retain parent references
                    this._placeTrace(payload);
                    delete this._pendingChildren[parent_tool_call_id];
                }, 30000);
                this._pendingChildren[parent_tool_call_id] = { payload, timer };
                return;
            }

            // --- Root trace: place directly ---
            this._placeTrace(payload);
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

        this._onToolCallStarted = (payload) => {
            const trace = this.traces.get(payload.trace_id);
            if (!trace) return;
            const iteration = trace.iterations.get(payload.iteration_id);
            if (!iteration) return;
            iteration.toolCalls.set(payload.tool_call_id, {
                tool_call_id: payload.tool_call_id,
                iteration_id: payload.iteration_id,
                tool_name: payload.tool_name,
                call_id: payload.call_id || null,
                args: payload.args || {},
                // Result fields are null until tool_call_completed arrives
                result: null,
                success: null,
                error: null,
                state_before: {},
                state_after: {},
                triggered_confirmation: false,
                confirmation_message: null,
                status: "running",  // Visual indicator that tool is in progress
            });
            // Check if any buffered child trace is waiting for this tool call
            const buffered = this._pendingChildren[payload.call_id];
            if (buffered) {
                clearTimeout(buffered.timer);
                delete this._pendingChildren[payload.call_id];
                // Place the child trace — parent tool call now exists
                this._placeTrace(buffered.payload);
            }
            // NEVER touch this.state.selectedId here — SIDE-05
        };

        this._onToolCallCompleted = (payload) => {
            const trace = this.traces.get(payload.trace_id);
            if (!trace) return;
            const iteration = trace.iterations.get(payload.iteration_id);
            if (!iteration) return;
            const tc = iteration.toolCalls.get(payload.tool_call_id);
            if (!tc) {
                // tool_call_completed arrived before tool_call_started (shouldn't happen
                // but be defensive) — create the entry directly
                iteration.toolCalls.set(payload.tool_call_id, {
                    tool_call_id: payload.tool_call_id,
                    iteration_id: payload.iteration_id,
                    tool_name: payload.tool_name,
                    call_id: payload.call_id || null,
                    args: payload.args || {},
                    result: payload.result,
                    success: payload.success,
                    error: payload.error || null,
                    state_before: {},
                    state_after: {},
                    triggered_confirmation: payload.triggered_confirmation || false,
                    confirmation_message: payload.confirmation_message || null,
                    status: "completed",
                });
                return;
            }
            // Update existing entry with result data
            tc.result = payload.result;
            tc.success = payload.success;
            tc.error = payload.error || null;
            tc.triggered_confirmation = payload.triggered_confirmation || false;
            tc.confirmation_message = payload.confirmation_message || null;
            tc.status = "completed";
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

            // Fire-and-forget IDB write — do NOT await
            if (!this.state.ephemeralMode) {
                writeTrace(trace).catch((err) => {
                    console.warn("[ai_debug] IDB write failed — switching to ephemeral mode:", err);
                    this.state.ephemeralMode = true;
                });
            }
        };

        // ----------------------------------------------------------------
        // IDB availability probe + hydration — runs before first render so no flash
        // ----------------------------------------------------------------
        onWillStart(async () => {
            const available = await probeIDB();
            if (!available) {
                console.warn("[ai_debug] IndexedDB unavailable — running in ephemeral mode");
                this.state.ephemeralMode = true;
                return;
            }
            // Hydrate from IDB before first render (PERS-02)
            const stored = await loadAllTraces();
            // Sort oldest-first so Map insertion order is chronological;
            // the template's .reverse() then yields newest-first display.
            stored.sort((a, b) =>
                (a.created_ts || new Date(a.started_at || 0).getTime()) -
                (b.created_ts || new Date(b.started_at || 0).getTime())
            );
            for (const plain of stored) {
                this.traces.set(plain.trace_id, hydrateTrace(plain));
            }
            // Auto-select first trace if any hydrated (SESS-03: auto-select when nothing selected)
            if (this.state.selectedId === null && this.traces.size > 0) {
                const firstKey = [...this.traces.keys()].at(-1); // at(-1) = top of reversed list
                this.state.selectedId = firstKey;
                this.state.selectedType = "trace";
            }
        });

        // ----------------------------------------------------------------
        // Bus lifecycle
        // ----------------------------------------------------------------
        onMounted(async () => {
            this.busService.subscribe("new_trace", this._onNewTrace);
            this.busService.subscribe("iteration", this._onIteration);
            this.busService.subscribe("tool_call_started", this._onToolCallStarted);
            this.busService.subscribe("tool_call_completed", this._onToolCallCompleted);
            this.busService.subscribe("loop_end", this._onLoopEnd);
            await this.busService.addChannel("ai_debug");
        });

        onWillUnmount(() => {
            this.busService.unsubscribe("new_trace", this._onNewTrace);
            this.busService.unsubscribe("iteration", this._onIteration);
            this.busService.unsubscribe("tool_call_started", this._onToolCallStarted);
            this.busService.unsubscribe("tool_call_completed", this._onToolCallCompleted);
            this.busService.unsubscribe("loop_end", this._onLoopEnd);
            this.busService.deleteChannel("ai_debug");
            // Clear any pending buffer timers to avoid orphan callbacks
            for (const key of Object.keys(this._pendingChildren)) {
                clearTimeout(this._pendingChildren[key].timer);
            }
            this._pendingChildren = {};
        });

        // ----------------------------------------------------------------
        // Post-render: auto-scroll to newest item + flash effect
        // ----------------------------------------------------------------
        onPatched(() => {
            // Indeterminate state for select-all checkbox (DOM property, not HTML attribute)
            if (this.selectAllRef.el) {
                this.selectAllRef.el.indeterminate = this.someChecked;
            }
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
    // Trace placement helper — unconditionally creates the trace entry
    // Used by both the root path and the pending-child re-attachment path
    // ----------------------------------------------------------------

    _placeTrace(payload) {
        const iterations = reactive(new Map());
        this.traces.set(payload.trace_id, {
            trace_id: payload.trace_id,
            agent_name: payload.agent_name || "Unknown Agent",
            model_name: payload.model_name || "",
            user_query: payload.user_query || "",
            status: "running",
            created_ts: Date.now(),
            started_at: new Date(),
            ended_at: null,
            duration_ms: null,
            expanded: true,
            iterations,
            instructions: payload.instructions || "",
            tools: payload.tools || [],
            state_snapshot: payload.state_snapshot || {},
            // Phase 13: parent linkage fields (null for root traces)
            parent_trace_id: payload.parent_trace_id || null,
            parent_tool_call_id: payload.parent_tool_call_id || null,
            session_id: payload.session_id || null,
        });
        this._lastArrivedId = payload.trace_id;
        this._flashId = payload.trace_id;
        this._needsScroll = true;
        if (this.state.selectedId === null) {
            this.state.selectedId = payload.trace_id;
            this.state.selectedType = "trace";
        }
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

    showFullQuery(_ev, query) {
        if (!this.dialog || !query) return;
        this.dialog.add(TextPopupDialog, {
            title: "User Query",
            content: query,
            language: "markdown",
        });
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
    // Sidebar tree — flat node list computed depth-first (TREE-01 to TREE-04)
    // No recursive OWL components; a single t-foreach renders this array.
    // ----------------------------------------------------------------

    /**
     * Returns a flat array of node descriptors representing the full sidebar
     * tree in display order (depth-first, newest-first within siblings).
     * Each descriptor carries { type, id, depth, ...refs }.
     *
     * Called during OWL render — reactive reads on this.traces and nested
     * reactive Maps are tracked here, so any mutation triggers re-render.
     */
    get sidebarNodes() {
        const nodes = [];
        // Root traces: those without a parent_trace_id, newest-first
        const rootTraces = [...this.traces.values()]
            .filter((t) => !t.parent_trace_id)
            .reverse();
        for (const trace of rootTraces) {
            this._collectTraceNodes(trace, 0, nodes);
        }
        return nodes;
    }

    /**
     * Recursively emit node descriptors for one trace and all its descendants.
     *
     * Depth rules (TREE-03):
     *   - The trace row itself is at `depth`.
     *   - Iteration rows and tool call rows within that trace share the same `depth`
     *     (flat within trace — indented only by inline padding, not by depth value).
     *   - Child subagent traces increment to `depth + 1`.
     *
     * @param {object} trace - reactive trace object
     * @param {number} depth - nesting depth (0 = root)
     * @param {Array}  nodes - accumulator array (mutated in place)
     */
    _collectTraceNodes(trace, depth, nodes) {
        // Push the trace row itself
        nodes.push({ type: "trace", id: trace.trace_id, depth, trace });

        // TREE-04: collapsed trace hides all descendants
        if (!trace.expanded) return;

        // Iterate iterations newest-first (matching existing template behavior)
        const iterKeys = [...trace.iterations.keys()].reverse();
        for (const iterId of iterKeys) {
            const iter = trace.iterations.get(iterId);
            if (!iter) continue;

            // Push iteration row (flat: same depth as trace)
            nodes.push({ type: "iter", id: iterId, depth, iter, trace });

            // Collapsed iteration: skip its tool calls and child traces
            if (!iter.expanded) continue;

            // Push tool call rows (flat: same depth as iteration)
            for (const [tcId, tc] of iter.toolCalls) {
                nodes.push({ type: "tc", id: tcId, depth, tc, iter, trace });

                // After each tool call, find child subagent traces that were
                // spawned by this tool call. Match by tc.call_id (the LLM
                // call_id), since parent_tool_call_id on child traces equals
                // the call_id field — NOT the UUID key (tcId).
                if (tc.call_id) {
                    for (const childTrace of this.traces.values()) {
                        if (
                            childTrace.parent_trace_id === trace.trace_id &&
                            childTrace.parent_tool_call_id === tc.call_id
                        ) {
                            this._collectTraceNodes(childTrace, depth + 1, nodes);
                        }
                    }
                }
            }
        }
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
        return this.busService.workerState === "CONNECTED"
            ? "connected"
            : "disconnected";
    }

    get statusLabel() {
        switch (this.busService.workerState) {
            case "CONNECTED":
                return "Connected";
            case "CONNECTING":
                return "Connecting...";
            case "DISCONNECTED":
                return "Disconnected";
            default:
                return "Connecting...";
        }
    }

    // ----------------------------------------------------------------
    // Selection state getters — used by template and deleteCheckedTraces
    // ----------------------------------------------------------------

    /**
     * Count of root (non-subagent) traces. Used by checkbox logic so that
     * subagent child traces don't inflate the expected denominator.
     */
    get rootTracesCount() {
        let count = 0;
        for (const t of this.traces.values()) {
            if (!t.parent_trace_id) count++;
        }
        return count;
    }

    get allChecked() {
        return this.rootTracesCount > 0 && this.state.checkedTraceIds.size === this.rootTracesCount;
    }

    get someChecked() {
        return this.state.checkedTraceIds.size > 0 && !this.allChecked;
    }

    // ----------------------------------------------------------------
    // Checkbox toggle and bulk delete methods
    // ----------------------------------------------------------------

    toggleTraceCheck(traceId) {
        if (this.state.checkedTraceIds.has(traceId)) {
            this.state.checkedTraceIds.delete(traceId);
        } else {
            this.state.checkedTraceIds.add(traceId);
        }
    }

    toggleSelectAll() {
        if (this.allChecked) {
            this.state.checkedTraceIds.clear();
        } else {
            for (const [id, trace] of this.traces) {
                if (!trace.parent_trace_id) {
                    this.state.checkedTraceIds.add(id);
                }
            }
        }
    }

    deleteCheckedTraces() {
        const ids = [...this.state.checkedTraceIds];
        if (ids.length === 0) return;
        // Clear checkbox selection first
        this.state.checkedTraceIds.clear();
        // Clear detail panel selection if the viewed trace is being deleted
        if (ids.includes(this.state.selectedId)) {
            this.state.selectedId = null;
            this.state.selectedType = null;
        }
        // Remove from reactive Map (triggers OWL re-render immediately)
        for (const id of ids) {
            this.traces.delete(id);
        }
        // Delete from IDB (fire-and-forget per item)
        for (const id of ids) {
            deleteTrace(id).catch((err) => {
                console.warn("[ai_debug] IDB delete failed for", id, err);
            });
        }
    }

    exportSelected() {
        const ids = [...this.state.checkedTraceIds];
        if (ids.length === 0) return;
        // Serialize each checked trace using the same format IDB stores.
        // JSON round-trip strips OWL reactive Proxies (same technique as writeTrace).
        const records = ids.map((id) => {
            const trace = this.traces.get(id);
            if (!trace) return null;
            return JSON.parse(JSON.stringify(serializeTrace(trace)));
        }).filter(Boolean);
        if (records.length === 0) return;
        const json = JSON.stringify(records, null, 2);
        const blob = new Blob([json], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        const today = new Date().toISOString().slice(0, 10);
        a.href = url;
        a.download = `ai-debug-traces-${today}.json`;
        a.click();
        URL.revokeObjectURL(url);
    }

    openImportPicker() {
        if (!this.fileInputRef.el) return;
        this.fileInputRef.el.click();
    }

    async onFileSelected(ev) {
        const file = ev.target.files[0];
        if (!file) return;
        ev.target.value = "";  // Reset so re-selecting same file triggers change event
        const text = await file.text();
        this._handleImportFile(text);
    }

    _handleImportFile(text) {
        let parsed;
        try {
            parsed = JSON.parse(text);
        } catch {
            if (this.dialog) {
                this.dialog.add(ImportPreviewDialog, {
                    traceCount: 0,
                    duplicateCount: 0,
                    onConfirm: () => {},
                    errorMessage: "Invalid file: could not parse JSON.",
                });
            }
            return;
        }

        // Validate: must be an array
        if (!Array.isArray(parsed)) {
            if (this.dialog) {
                this.dialog.add(ImportPreviewDialog, {
                    traceCount: 0,
                    duplicateCount: 0,
                    onConfirm: () => {},
                    errorMessage: "Invalid file: expected a JSON array of traces.",
                });
            }
            return;
        }

        // Validate each element: must have trace_id (string) and iterations (array)
        for (const item of parsed) {
            if (
                !item ||
                typeof item !== "object" ||
                typeof item.trace_id !== "string" ||
                !item.trace_id ||
                !Array.isArray(item.iterations)
            ) {
                if (this.dialog) {
                    this.dialog.add(ImportPreviewDialog, {
                        traceCount: 0,
                        duplicateCount: 0,
                        onConfirm: () => {},
                        errorMessage: "Invalid file: each trace must have a trace_id string and iterations array.",
                    });
                }
                return;
            }
        }

        // Count duplicates (traces with same ID already in store)
        const duplicateCount = parsed.filter((r) => this.traces.has(r.trace_id)).length;

        if (this.dialog) {
            this.dialog.add(ImportPreviewDialog, {
                traceCount: parsed.length,
                duplicateCount,
                onConfirm: () => this._applyImport(parsed),
            });
        }
    }

    onResizeStart(ev) {
        ev.preventDefault();
        const startX = ev.clientX;
        const startWidth = this.state.sidebarWidth;

        const onMove = (e) => {
            const delta = e.clientX - startX;
            const newWidth = Math.max(180, Math.min(600, startWidth + delta));
            this.state.sidebarWidth = newWidth;
        };

        const onUp = () => {
            document.removeEventListener("pointermove", onMove);
            document.removeEventListener("pointerup", onUp);
            document.body.style.cursor = "";
            document.body.style.userSelect = "";
        };

        document.addEventListener("pointermove", onMove);
        document.addEventListener("pointerup", onUp);
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
    }

    _applyImport(records) {
        // Sort oldest-first so Map insertion order is chronological;
        // the template's .reverse() then yields newest-first display.
        records.sort((a, b) =>
            (a.created_ts || new Date(a.started_at || 0).getTime()) -
            (b.created_ts || new Date(b.started_at || 0).getTime())
        );
        for (const record of records) {
            const hydrated = hydrateTrace(record);
            this.traces.set(record.trace_id, hydrated);
            // Fire-and-forget IDB write — overwrites if duplicate (same pattern as _onLoopEnd)
            if (!this.state.ephemeralMode) {
                writeTrace(hydrated).catch((err) => {
                    console.warn("[ai_debug] IDB write failed during import:", err);
                });
            }
        }
    }
}
