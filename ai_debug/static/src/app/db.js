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
        model_name: trace.model_name,
        user_query: trace.user_query,
        status: trace.status,
        duration_ms: trace.duration_ms,
        instructions: trace.instructions,
        state_snapshot: trace.state_snapshot,
        parent_trace_id: trace.parent_trace_id,
        parent_tool_call_id: trace.parent_tool_call_id,
        session_id: trace.session_id,
        // Map → array of [iterationId, iterationRecord] pairs
        iterations: [...trace.iterations.entries()].map(([iterId, iter]) => [
            iterId,
            {
                iteration_id: iter.iteration_id,
                trace_id: iter.trace_id,
                iteration_index: iter.iteration_index,
                has_error: iter.has_error,
                is_final: iter.is_final,
                error: iter.error,
                messages_sent: iter.messages_sent,
                raw_response: iter.raw_response,
                // Phase 17: token/timing/provider fields
                // tokens is a plain {input, output, cache_read, cache_write, reasoning, total} —
                // JSON-serializable; writeTrace's JSON.parse(JSON.stringify(...)) strips OWL Proxies.
                tokens: iter.tokens,
                duration_ms: iter.duration_ms,
                ai_provider: iter.ai_provider,
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
                    },
                ]),
            },
        ]),
    };
}

/**
 * Write a completed trace to IndexedDB.
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
