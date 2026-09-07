/** @odoo-module **/
import { IndexedDB } from "@web/core/utils/indexed_db";

const DB_NAME = "ai_debug_traces";
const DB_VERSION = 1;
const STORE = "traces";

const idb = new IndexedDB(DB_NAME, DB_VERSION);

/**
 * Probe whether IndexedDB is available in this session.
 * Returns true if available, false if blocked (e.g., private browsing).
 */
export async function probeIDB() {
    try {
        await idb.getAllKeys(STORE);
        return true;
    } catch {
        return false;
    }
}

/**
 * Serialize a trace from the reactive store into a plain IDB-storable record.
 * Maps are converted to arrays of [key, value] entries (structured clone would
 * preserve Maps, but explicit serialization avoids Proxy-related issues and
 * produces a well-defined schema for Phase 11 hydration and Phase 12 export).
 *
 * Note: expanded (UI-only state) is intentionally excluded.
 */
export function serializeTrace(trace) {
    return {
        trace_id: trace.trace_id,
        storedAt: Date.now(),
        created_ts: trace.created_ts,
        agent_name: trace.agent_name,
        trace_kind: trace.trace_kind,
        trace_label: trace.trace_label,
        ai_provider: trace.ai_provider,
        model_name: trace.model_name,
        user_query: trace.user_query,
        status: trace.status,
        duration_ms: trace.duration_ms,
        duration_kind: trace.duration_kind,
        instructions: trace.instructions,
        state_snapshot: trace.state_snapshot,
        parent_trace_id: trace.parent_trace_id,
        parent_session_id: trace.parent_session_id,
        parent_request_uuid: trace.parent_request_uuid,
        parent_tool_call_id: trace.parent_tool_call_id,
        session_id: trace.session_id,
        _payload_excluded: trace._payload_excluded,
        exchange_uuid: trace.exchange_uuid,
        request_uuid: trace.request_uuid,
        round_no: trace.round_no,
        request_state: trace.request_state,
        request_phase: trace.request_phase,
        phase: trace.phase,
        partial: trace.partial,
        termination_reason: trace.termination_reason,
        termination_source: trace.termination_source,
        exchange_result: trace.exchange_result,
        final_output: trace.final_output,
        error: trace.error,
        // Map → array of [iterationId, iterationRecord] pairs
        iterations: [...trace.iterations.entries()].map(([iterId, iter]) => [
            iterId,
            {
                iteration_id: iter.iteration_id,
                trace_id: iter.trace_id,
                iteration_index: iter.iteration_index,
                exchange_uuid: iter.exchange_uuid,
                request_uuid: iter.request_uuid,
                round_no: iter.round_no,
                request_state: iter.request_state,
                request_phase: iter.request_phase,
                phase: iter.phase,
                has_error: iter.has_error,
                is_final: iter.is_final,
                error: iter.error,
                messages_sent: iter.messages_sent,
                request_body: iter.request_body,
                request_label: iter.request_label,
                raw_response: iter.raw_response,
                response_label: iter.response_label,
                _payload_excluded: iter._payload_excluded,
                // Phase 17: token/timing/provider fields
                // tokens is a plain {input, output, cache_read, cache_write, reasoning, total} —
                // JSON-serializable; writeTrace's JSON.parse(JSON.stringify(...)) strips OWL Proxies.
                tokens: iter.tokens,
                duration_ms: iter.duration_ms,
                duration_kind: iter.duration_kind,
                ai_provider: iter.ai_provider,
                model_name: iter.model_name,
                provider_api: iter.provider_api,
                tools: iter.tools,
                // Map → array of [toolCallId, toolCallRecord] pairs
                toolCalls: [...iter.toolCalls.entries()].map(([tcId, tc]) => [
                    tcId,
                    {
                        tool_call_id: tc.tool_call_id,
                        iteration_id: tc.iteration_id,
                        tool_name: tc.tool_name,
                        success: tc.success,
                        args: tc.args,
                        result: tc.result,
                        error: tc.error,
                        state_before: tc.state_before,
                        state_after: tc.state_after,
                        call_id: tc.call_id,
                        triggered_confirmation: tc.triggered_confirmation,
                        confirmation_message: tc.confirmation_message,
                        status: tc.status,
                        child_phase: tc.child_phase,
                        child_session_id: tc.child_session_id,
                        child_request_uuid: tc.child_request_uuid,
                        duration_ms: tc.duration_ms,
                    },
                ]),
            },
        ]),
    };
}

/**
 * Write the latest captured trace snapshot to IndexedDB, including active traces.
 * Returns a Promise — do NOT await at the call site (fire-and-forget).
 * Caller should .catch() to detect mid-session failures.
 *
 * Note: trace_id is a UUID hex string from the backend (uuid.uuid4().hex)
 * and is safe to use directly as the IDB key.
 */
export function writeTrace(trace) {
    // JSON round-trip strips OWL reactive Proxies that IDB's structured clone
    // cannot handle (DataCloneError). Dates become ISO strings — Phase 11
    // hydration must parse them back.
    const record = JSON.parse(JSON.stringify(serializeTrace(trace)));
    return idb.write(STORE, trace.trace_id, record);
}

/**
 * Delete a trace record from IndexedDB by trace_id.
 */
export async function deleteTrace(traceId) {
    return idb.delete(STORE, traceId);
}

/**
 * Delete multiple trace records from IndexedDB.
 * Used by cascade delete to remove a root trace and all its descendants.
 */
export async function deleteTraces(traceIds) {
    if (!traceIds.length) return;
    for (const id of traceIds) {
        await idb.delete(STORE, id);
    }
}

/**
 * Load all stored traces from IndexedDB.
 * Returns an array of plain serialized trace records.
 * Returns [] if IDB is unavailable or store is empty.
 *
 * Note: records contain iterations as [iterId, iterRecord] pair arrays —
 * hydrateTrace() in app.js reconstructs the reactive Maps.
 */
export async function loadAllTraces() {
    try {
        const entries = await idb.getAllEntries(STORE);
        return entries.map(({ value }) => value);
    } catch {
        return [];
    }
}
