/** @odoo-module **/
import { iterationMessages, iterationTools, normalizeTokens } from "./event_payload";

const PHASES = ["prepared", "submitted", "result_received", "result_consumed", "child_applied", "child_settled", "completed"];
const makeMap = () => new Map();

function assignDefined(target, source, fields) {
    for (const field of fields) {
        if (source[field] !== undefined) target[field] = source[field];
    }
}

function updateProgress(target, payload) {
    if (payload.phase === "child_applied") return;
    const phase = payload.phase ?? (payload.type === "new_trace" ? "prepared" : null);
    const round = payload.round_no ?? payload.iteration_index ?? target.round_no;
    if ((round ?? 0) < (target.round_no ?? 0)) return;
    if (round === target.round_no && PHASES.indexOf(phase) < PHASES.indexOf(target.phase)) return;
    if ((round ?? 0) > (target.round_no ?? 0)) target.phase = null;
    if (phase) target.phase = phase;
    if (round != null) target.round_no = round;
    target.request_uuid = payload.request_uuid ?? payload.iteration_id ?? target.request_uuid;
    target.request_state = payload.state ?? payload.request_state ?? target.request_state;
    target.request_phase = payload.request_phase ?? target.request_phase;
}

function ensureIteration(trace, payload, newMap) {
    const id = payload.iteration_id ?? payload.request_uuid;
    if (!id) return null;
    if (!trace.iterations.has(id)) {
        trace.iterations.set(id, {
            iteration_id: id, trace_id: trace.trace_id, request_uuid: id,
            exchange_uuid: trace.exchange_uuid,
            iteration_index: payload.iteration_index ?? payload.round_no,
            round_no: payload.round_no ?? payload.iteration_index,
            expanded: true, toolCalls: newMap(), has_error: false,
            messages_sent: [], tools: [], raw_response: null, request_body: null,
            tokens: null, duration_ms: null, duration_kind: null,
        });
    }
    return trace.iterations.get(id);
}

function ensureTool(iteration, payload) {
    if (!iteration.toolCalls.has(payload.tool_call_id)) {
        iteration.toolCalls.set(payload.tool_call_id, {
            tool_call_id: payload.tool_call_id, iteration_id: iteration.iteration_id,
            tool_name: "Unknown Tool", call_id: null, args: {}, result: null,
            success: null, error: null, state_before: {}, state_after: {},
            triggered_confirmation: false, confirmation_message: null,
            status: "running", expanded: true,
        });
    }
    return iteration.toolCalls.get(payload.tool_call_id);
}

/** Reduce captured bus facts only; absent starts create inspectable partial traces. */
export function reduceTraceEvent(traces, payload, newMap = makeMap) {
    if (!payload.trace_id) return null;
    if (!traces.has(payload.trace_id)) {
        traces.set(payload.trace_id, {
            trace_id: payload.trace_id, exchange_uuid: payload.exchange_uuid ?? payload.trace_id,
            agent_name: "Unknown Agent", user_query: "", instructions: "", state_snapshot: {},
            status: "running", partial: true, created_ts: Date.now(), expanded: true,
            duration_ms: null, duration_kind: null, ai_provider: null, model_name: "",
            iterations: newMap(),
        });
    }
    const trace = traces.get(payload.trace_id);
    assignDefined(trace, payload, ["exchange_uuid", "session_id"]);
    if (trace.status === "running") updateProgress(trace, payload);

    if (payload.type === "new_trace") {
        assignDefined(trace, payload, [
            "agent_name", "trace_kind", "trace_label", "user_query", "instructions", "state_snapshot",
            "parent_trace_id", "parent_session_id", "parent_request_uuid", "parent_tool_call_id",
            "_payload_excluded",
        ]);
        trace.partial = false;
    } else if (payload.type === "loop_end") {
        trace.status = ["success", "completed"].includes(payload.termination_reason) ? "success"
            : payload.termination_reason === "max_iterations" ? "max_iterations" : "error";
        assignDefined(trace, payload, [
            "phase", "termination_reason", "termination_source", "exchange_result", "final_output", "error",
            "duration_ms", "duration_kind", "request_state", "request_uuid", "round_no",
        ]);
    } else {
        const iteration = ensureIteration(trace, payload, newMap);
        if (!iteration) return trace;
        updateProgress(iteration, payload);
        iteration.iteration_index = payload.iteration_index ?? payload.round_no ?? iteration.iteration_index;
        if (payload.type === "iteration") {
            // Prepared replays fill request facts, but must never erase a received response.
            assignDefined(iteration, payload, ["request_body", "request_label", "response_label", "_payload_excluded"]);
            if (payload.messages_sent || payload.request_body || payload.message_summary) {
                iteration.messages_sent = iterationMessages(payload);
            }
            if (payload.tools || payload.request_body) iteration.tools = iterationTools(payload);
            const response = payload.raw_response ?? payload.response_summary;
            if (response != null) iteration.raw_response = response;
            if (payload.phase !== "prepared") {
                assignDefined(iteration, payload, ["error", "is_final", "duration_ms", "duration_kind"]);
                if (payload.error !== undefined) iteration.has_error = !!payload.error;
                if (payload.tokens != null) iteration.tokens = normalizeTokens(payload.tokens);
                iteration.ai_provider = payload.provider ?? iteration.ai_provider;
                iteration.model_name = payload.model_name ?? iteration.model_name;
                iteration.provider_api = payload.provider_api ?? iteration.provider_api;
            }
        } else if (payload.tool_call_id) {
            const tc = ensureTool(iteration, payload);
            assignDefined(tc, payload, ["tool_name", "call_id", "args"]);
            if (payload.type === "tool_call_completed") {
                const status = payload.status ?? (payload.triggered_confirmation ? "waiting_confirmation" : "completed");
                if (tc.status !== "completed" || status === "completed") {
                    assignDefined(tc, payload, ["result", "success", "error", "state_before", "state_after", "duration_ms"]);
                    tc.status = status;
                    tc.triggered_confirmation ||= !!payload.triggered_confirmation;
                    tc.confirmation_message = payload.confirmation_message ?? tc.confirmation_message;
                }
            } else if (payload.phase === "child_applied") {
                // Application is a parent-side fact, separate from child settlement and tool completion.
                tc.child_phase = "child_applied";
                assignDefined(tc, payload, ["child_session_id", "child_request_uuid"]);
            }
        }
    }
    trace.ai_provider = payload.provider ?? trace.ai_provider;
    trace.model_name = payload.model_name ?? trace.model_name;
    return trace;
}

/** Durable children match their exact request and UUID tool key. Raw call IDs are legacy-only. */
export function parentTool(traces, child) {
    const trace = traces.get(child.parent_trace_id);
    if (!trace || trace === child || !child.parent_tool_call_id) return null;
    if (child.parent_session_id && trace.session_id !== child.parent_session_id) return null;
    for (const iteration of trace.iterations.values()) {
        if (child.parent_request_uuid && iteration.iteration_id !== child.parent_request_uuid) continue;
        for (const tc of iteration.toolCalls.values()) {
            if (tc.tool_call_id === child.parent_tool_call_id || (
                !child.parent_request_uuid && !child.parent_session_id && tc.call_id === child.parent_tool_call_id
            )) return { trace, iteration, tc };
        }
    }
    return null;
}

export function collectSidebarNodes(traces) {
    const children = new Map();
    const roots = [];
    for (const trace of traces.values()) {
        const parent = parentTool(traces, trace);
        if (parent) {
            const key = parent.tc.tool_call_id;
            if (!children.has(key)) children.set(key, []);
            children.get(key).push(trace);
        } else roots.push(trace);
    }
    const nodes = [];
    const seen = new Set();
    function collect(trace, depth) {
        if (seen.has(trace.trace_id)) return;
        seen.add(trace.trace_id);
        nodes.push({ type: "trace", id: trace.trace_id, depth, trace });
        if (!trace.expanded) return;
        const iterations = [...trace.iterations.values()].sort((a, b) => (b.iteration_index ?? 0) - (a.iteration_index ?? 0));
        for (const iter of iterations) {
            nodes.push({ type: "iter", id: iter.iteration_id, depth, iter, trace });
            if (!iter.expanded) continue;
            for (const [id, tc] of iter.toolCalls) {
                const nested = children.get(id) ?? [];
                nodes.push({ type: "tc", id, depth, tc, iter, trace, hasChildren: !!nested.length });
                if (tc.expanded !== false) for (const child of nested) collect(child, depth + 1);
            }
        }
    }
    for (const root of roots.reverse()) collect(root, 0);
    return nodes;
}

/** The saved snapshot is captured history, including active phases and unresolved links. */
export function hydrateTrace(plain, newMap = makeMap) {
    const iterations = newMap();
    for (const [id, iter] of plain.iterations ?? []) {
        const toolCalls = newMap();
        for (const [tcId, tc] of iter.toolCalls ?? []) {
            toolCalls.set(tcId, { ...tc, status: tc.status ?? "completed", expanded: true });
        }
        iterations.set(id, { ...iter, expanded: true, toolCalls, tokens: iter.tokens ?? null,
            duration_ms: iter.duration_ms ?? null, tools: iter.tools ?? [] });
    }
    return { ...plain, created_ts: plain.created_ts || plain.storedAt || 0,
        ai_provider: plain.ai_provider ?? null, model_name: plain.model_name ?? "",
        duration_ms: plain.duration_ms ?? null, duration_kind: plain.duration_kind ?? null,
        expanded: false, hydrated: true, iterations };
}
