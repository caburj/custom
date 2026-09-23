/** @odoo-module **/
import { Component, proxy, onMounted, onWillStart, onWillUnmount, onPatched, signal } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { MainComponentsContainer } from "@web/core/main_components_container";
import { LoopDetail } from "./detail/loop_detail";
import { IterationDetail } from "./detail/iter_detail";
import { ToolCallDetail } from "./detail/tc_detail";
import { probeIDB, writeTrace, deleteTraces, loadAllTraces, serializeTrace } from "./db";
import { ImportPreviewDialog } from "./import_dialog";
import { TextPopupDialog } from "./detail/text_popup";
import { formatTokens, formatDuration } from "./format_metrics";
import { reduceTraceEvent, collectSidebarNodes, parentTool, hydrateTrace } from "./trace_store";

const AI_DEBUG_CHANNEL = "ai_debug";

export class AiDebugApp extends Component {
    static template = "ai_debug.App";
    static components = { LoopDetail, IterationDetail, ToolCallDetail, MainComponentsContainer };

    setup() {
        this.busService = useService("bus_service");

        // Trace data store — proxy() wraps the Map so OWL's render function
        // observes mutations (.set/.delete/.clear) and triggers re-renders.
        // Nested reactive Maps (iterations, toolCalls) inherit the render
        // callback when accessed through this proxy chain.
        this.traces = proxy(new Map());

        // Selection state — completely separate from trace data (SIDE-05)
        this.state = proxy({
            selectedId: null,
            selectedType: null,   // 'trace' | 'iteration' | 'tool_call'
            ephemeralMode: false, // true when IDB is unavailable (private browsing or write failure)
            checkedTraceIds: new Set(),  // Phase 11: checkbox selection for bulk delete
            sidebarWidth: 420,
            nestingMode: (() => {
                try { return localStorage.getItem("ai_debug.nestingMode") || "indent"; }
                catch { return "indent"; }
            })(),
        });

        // Formatting utilities bound for template use (Phase 18)
        this.formatTokens = formatTokens;
        this.formatDuration = formatDuration;

        // Sidebar DOM ref for auto-scroll
        this.sidebarRef = signal.ref();
        // Select-all checkbox DOM ref for indeterminate state sync
        this.selectAllRef = signal.ref();
        // Hidden file input ref for import file picker
        this.fileInputRef = signal.ref();
        try {
            this.dialog = useService("dialog");
        } catch {
            this.dialog = null;
        }
        this._needsScroll = false;
        this._flashId = null;
        this._lastArrivedId = null;
        // Every captured event is immediately inspectable and persisted, including
        // partial children whose parent has not reached this browser yet.
        this._onTraceEvent = (payload) => {
            const isNew = !this.traces.has(payload.trace_id);
            const trace = reduceTraceEvent(this.traces, payload, () => proxy(new Map()));
            if (!trace) return;
            if (isNew || payload.type === "iteration") {
                this._lastArrivedId = payload.iteration_id ?? payload.trace_id;
                this._needsScroll = true;
            }
            if (isNew) this._flashId = payload.trace_id;
            if (this.state.selectedId === null) {
                this.state.selectedId = trace.trace_id;
                this.state.selectedType = "trace";
            }
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
                (a.created_ts || a.storedAt || 0) -
                (b.created_ts || b.storedAt || 0)
            );
            for (const plain of stored) {
                this.traces.set(plain.trace_id, hydrateTrace(plain, () => proxy(new Map())));
            }
            // Auto-select newest root trace if nothing is selected (SESS-03).
            // Must filter to root traces only — never auto-select a subagent
            // child trace, as that would confuse the detail panel context.
            if (this.state.selectedId === null && this.traces.size > 0) {
                let bestTrace = null;
                for (const trace of this.traces.values()) {
                    if (!parentTool(this.traces, trace)) {
                        if (!bestTrace || (trace.created_ts || 0) > (bestTrace.created_ts || 0)) {
                            bestTrace = trace;
                        }
                    }
                }
                if (bestTrace) {
                    this.state.selectedId = bestTrace.trace_id;
                    this.state.selectedType = "trace";
                }
            }
        });

        // ----------------------------------------------------------------
        // Bus lifecycle
        // ----------------------------------------------------------------
        onMounted(async () => {
            this.busService.subscribe("new_trace", this._onTraceEvent);
            this.busService.subscribe("request_state", this._onTraceEvent);
            this.busService.subscribe("iteration", this._onTraceEvent);
            this.busService.subscribe("tool_call_started", this._onTraceEvent);
            this.busService.subscribe("tool_call_completed", this._onTraceEvent);
            this.busService.subscribe("tool_call_progress", this._onTraceEvent);
            this.busService.subscribe("loop_end", this._onTraceEvent);
            await this.busService.addChannel(AI_DEBUG_CHANNEL);
        });

        onWillUnmount(() => {
            this.busService.deleteChannel(AI_DEBUG_CHANNEL);
            this.busService.unsubscribe("new_trace", this._onTraceEvent);
            this.busService.unsubscribe("request_state", this._onTraceEvent);
            this.busService.unsubscribe("iteration", this._onTraceEvent);
            this.busService.unsubscribe("tool_call_started", this._onTraceEvent);
            this.busService.unsubscribe("tool_call_completed", this._onTraceEvent);
            this.busService.unsubscribe("tool_call_progress", this._onTraceEvent);
            this.busService.unsubscribe("loop_end", this._onTraceEvent);
        });

        // ----------------------------------------------------------------
        // Post-render: auto-scroll to newest item + flash effect
        // ----------------------------------------------------------------
        onPatched(() => {
            // Indeterminate state for select-all checkbox (DOM property, not HTML attribute)
            if (this.selectAllRef()) {
                this.selectAllRef().indeterminate = this.someChecked;
            }
            if (this._needsScroll && this._lastArrivedId && this.sidebarRef()) {
                const el = this.sidebarRef().querySelector(
                    `[data-node-id="${this._lastArrivedId}"]`,
                );
                if (el) {
                    el.scrollIntoView({ behavior: "smooth", block: "nearest" });
                }
                this._needsScroll = false;
            }
            if (this._flashId && this.sidebarRef()) {
                const el = this.sidebarRef().querySelector(
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

    toggleNestingMode() {
        this.state.nestingMode = this.state.nestingMode === "lines" ? "indent" : "lines";
        try { localStorage.setItem("ai_debug.nestingMode", this.state.nestingMode); }
        catch { /* private browsing or quota — silently ignore */ }
    }

    showFullQuery(ev, query) {
        ev.stopPropagation();
        if (!this.dialog || !query) return;
        this.dialog.add(TextPopupDialog, {
            title: "User Query",
            content: query,
            language: "markdown",
        });
    }

    toggleExpand(idOrTraceId, typeOrIterationId, toolCallId) {
        // Called as toggleExpand(traceId, 'trace') for loops
        // Called as toggleExpand(traceId, iterationId) for iterations
        // Called as toggleExpand(traceId, iterationId, toolCallId) for tool calls
        if (typeOrIterationId === "trace") {
            const trace = this.traces.get(idOrTraceId);
            if (trace) trace.expanded = !trace.expanded;
        } else if (toolCallId) {
            // Three args: toggle a tool call's child subagent traces
            const trace = this.traces.get(idOrTraceId);
            if (!trace) return;
            const iteration = trace.iterations.get(typeOrIterationId);
            if (!iteration) return;
            const tc = iteration.toolCalls.get(toolCallId);
            if (tc) tc.expanded = !tc.expanded;
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

    // Depth staircase line constants — keep in sync with SCSS row heights
    static DEPTH_LINE_BASE_X = 6;
    static DEPTH_LINE_STEP_X = 4;
    static DEPTH_LINE_TRANSITION_H = 16;
    static DEPTH_LINE_COLORS = ["#3b82f6", "#14b8a6", "#a855f7", "#f59e0b", "#f43f5e"];
    static ROW_H_TRACE = 44;
    static ROW_H_DEFAULT = 34;

    /**
     * Returns a flat array of node descriptors representing the full sidebar
     * tree in display order (depth-first, newest-first within siblings).
     * Each descriptor carries { type, id, depth, ...refs }.
     *
     * Called during OWL render — reactive reads on this.traces and nested
     * reactive Maps are tracked here, so any mutation triggers re-render.
     */
    /**
     * Total pixel height of all sidebar rows — used for SVG viewBox height.
     * Coupled to CSS: trace rows = 44px, iter/tc rows = 34px.
     */
    get depthLineTotalHeight() {
        const C = this.constructor;
        return this.sidebarNodes.reduce(
            (h, n) => h + (n.type === "trace" ? C.ROW_H_TRACE : C.ROW_H_DEFAULT), 0
        );
    }

    /**
     * Compute SVG path descriptors for the depth staircase line.
     * Returns [{d, color}, ...] — vertical segments + S-curve transitions.
     */
    get depthLinePaths() {
        const nodes = this.sidebarNodes;
        if (nodes.length === 0) return [];

        const C = this.constructor;
        const BX = C.DEPTH_LINE_BASE_X;
        const SX = C.DEPTH_LINE_STEP_X;
        const TH = C.DEPTH_LINE_TRANSITION_H;
        const COLORS = C.DEPTH_LINE_COLORS;

        // Pass 1: compute y-positions from known row heights
        let y = 0;
        const pos = [];
        for (const node of nodes) {
            const h = node.type === "trace" ? C.ROW_H_TRACE : C.ROW_H_DEFAULT;
            pos.push({ top: y, bottom: y + h, depth: Math.min(node.depth, 4) });
            y += h;
        }

        // Pass 2: group consecutive rows by depth
        const groups = [];
        let gStart = 0;
        for (let i = 1; i <= pos.length; i++) {
            if (i === pos.length || pos[i].depth !== pos[gStart].depth) {
                groups.push({
                    depth: pos[gStart].depth,
                    yTop: pos[gStart].top,
                    yBot: pos[i - 1].bottom,
                });
                gStart = i;
            }
        }

        // Pass 3: build path segments
        const paths = [];
        for (let g = 0; g < groups.length; g++) {
            const grp = groups[g];
            const x = BX + grp.depth * SX;
            const color = COLORS[grp.depth] || COLORS[4];

            // Vertical extent, trimmed by transition zones
            let yStart = grp.yTop;
            let yEnd = grp.yBot;
            if (g > 0) yStart += TH / 2;
            if (g < groups.length - 1) yEnd -= TH / 2;

            if (yEnd > yStart) {
                paths.push({ d: `M ${x},${yStart} L ${x},${yEnd}`, color });
            }

            // S-curve transition to next group
            if (g < groups.length - 1) {
                const next = groups[g + 1];
                const nx = BX + next.depth * SX;
                const boundary = grp.yBot;
                const cy0 = boundary - TH / 2;
                const cy1 = boundary + TH / 2;
                const curveColor = COLORS[Math.max(grp.depth, next.depth)] || COLORS[4];
                paths.push({
                    d: `M ${x},${cy0} C ${x},${boundary} ${nx},${boundary} ${nx},${cy1}`,
                    color: curveColor,
                });
            }
        }

        return paths;
    }

    get sidebarNodes() {
        return collectSidebarNodes(this.traces);
    }

    /**
     * Recursively collect all descendant trace IDs of a given trace.
     * A descendant is any trace whose parent_trace_id matches traceId,
     * plus recursively their descendants (any depth).
     *
     * Used by deleteCheckedTraces to cascade deletion to all child subagent traces.
     *
     * @param {string} traceId - the root trace ID to collect descendants for
     * @returns {string[]} array of descendant trace IDs (not including traceId itself)
     */
    _collectDescendantIds(traceId) {
        const descendants = [];
        for (const [id, trace] of this.traces) {
            if (trace.parent_trace_id === traceId) {
                descendants.push(id);
                descendants.push(...this._collectDescendantIds(id));
            }
        }
        return descendants;
    }

    /**
     * Compute trace-level token and timing aggregates across all iterations.
     *
     * Called from OWL templates — reading iter.tokens and iter.duration_ms through
     * the reactive proxy chain (trace.iterations.values()) triggers re-render whenever
     * any iteration's token data changes. This is the reactive data layer for SIDE-02:
     * Phase 18 templates reading getTraceTotals(trace).total_tokens will re-render as
     * each new iteration event arrives.
     *
     * Returns raw numbers only — no formatting (Phase 18's concern).
     *
     * @param {object} trace - reactive trace object with iterations Map
     * @returns {{ total_tokens, total_duration_ms, total_input, total_output, total_cached, total_reasoning }}
     */
    getTraceTotals(trace) {
        let total_tokens = 0, total_duration_ms = 0,
            total_input = 0, total_output = 0,
            total_cached = 0, total_reasoning = 0;
        let has_token_metrics = false;
        let has_duration_metrics = false;
        for (const iter of trace.iterations.values()) {
            const t = iter.tokens;
            if (t) {
                has_token_metrics = true;
                total_input += t.input || 0;
                total_output += t.output || 0;
                total_cached += t.cache_read || 0;
                total_reasoning += t.reasoning || 0;
                total_tokens += t.total || 0;
            }
            if (iter.duration_ms !== null && iter.duration_ms !== undefined) {
                has_duration_metrics = true;
                total_duration_ms += iter.duration_ms;
            }
        }
        return {
            total_tokens,
            total_duration_ms,
            total_input,
            total_output,
            total_cached,
            total_reasoning,
            has_token_metrics,
            has_duration_metrics,
        };
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
            if (!parentTool(this.traces, t)) count++;
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
                if (!parentTool(this.traces, trace)) {
                    this.state.checkedTraceIds.add(id);
                }
            }
        }
    }

    deleteCheckedTraces() {
        const ids = [...this.state.checkedTraceIds];
        if (ids.length === 0) return;
        // Collect all descendant trace IDs for cascade delete
        const allIds = [...ids];
        for (const id of ids) {
            allIds.push(...this._collectDescendantIds(id));
        }
        // Deduplicate (a descendant could also be checked, or appear via multiple paths)
        const uniqueIds = [...new Set(allIds)];
        // Clear checkbox selection first
        this.state.checkedTraceIds.clear();
        // Clear detail panel selection if the viewed item belongs to a deleted trace
        if (uniqueIds.includes(this.state.selectedId) || uniqueIds.includes(this.selectedTraceId)) {
            this.state.selectedId = null;
            this.state.selectedType = null;
        }
        // Remove from reactive Map (triggers OWL re-render immediately)
        for (const id of uniqueIds) {
            this.traces.delete(id);
        }
        // Delete from IDB in a single transaction (fire-and-forget)
        deleteTraces(uniqueIds).catch((err) => {
            console.warn("[ai_debug] IDB cascade delete failed:", err);
        });
    }

    exportSelected() {
        const ids = [...this.state.checkedTraceIds];
        if (ids.length === 0) return;
        // Expand to include all descendant traces (subagent children) before
        // serializing — mirrors the proven deleteCheckedTraces() cascade pattern.
        const allIds = [...ids];
        for (const id of ids) {
            allIds.push(...this._collectDescendantIds(id));
        }
        const uniqueIds = [...new Set(allIds)];
        // Serialize each trace using the same format IDB stores.
        // JSON round-trip strips OWL reactive Proxies (same technique as writeTrace).
        const records = uniqueIds.map((id) => {
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
        if (!this.fileInputRef()) return;
        this.fileInputRef().click();
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
            (a.created_ts || a.storedAt || 0) -
            (b.created_ts || b.storedAt || 0)
        );
        for (const record of records) {
            const hydrated = hydrateTrace(record, () => proxy(new Map()));
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
