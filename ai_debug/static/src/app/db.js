/** @odoo-module **/
import { IndexedDB } from "@web/core/utils/indexed_db";

const DB_NAME = "ai_debug_traces";
const DB_VERSION = 1;
const STORE = "traces";

const idb = new IndexedDB(DB_NAME, DB_VERSION);
// Ensure the "traces" store is registered with the IndexedDB utility so that
// onupgradeneeded creates it when the DB is opened (e.g. after external deletion).
// Without this, direct idb.execute() calls skip store registration (only read/write/
// getAllKeys add to _tables) and the store won't exist after DB recreation.
idb._tables.add(STORE);

/**
 * Probe whether IndexedDB is available in this session.
 * Returns true if available, false if blocked (e.g., private browsing).
 *
 * Technique: idb.execute() passes db to the callback when open succeeds,
 * or calls callback(undefined) when onerror fires. We distinguish by checking
 * if db is truthy.
 */
export async function probeIDB() {
    const result = await idb.execute((db) => (db ? "ok" : null));
    return result === "ok";
}

/**
 * Serialize a trace from the reactive store into a plain IDB-storable record.
 * Maps are converted to arrays of [key, value] entries (structured clone would
 * preserve Maps, but explicit serialization avoids Proxy-related issues and
 * produces a well-defined schema for Phase 11 hydration and Phase 12 export).
 *
 * Note: expanded (UI-only state) is intentionally excluded.
 * Note: Date objects are preserved as-is — IDB structured clone handles them.
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
        started_at: trace.started_at,
        ended_at: trace.ended_at,
        duration_ms: trace.duration_ms,
        instructions: trace.instructions,
        tools: trace.tools,
        state_snapshot: trace.state_snapshot,
        // Map → array of [iterationId, iterationRecord] pairs
        iterations: [...trace.iterations.entries()].map(([iterId, iter]) => [
            iterId,
            {
                iteration_id: iter.iteration_id,
                trace_id: iter.trace_id,
                iteration_index: iter.iteration_index,
                has_error: iter.has_error,
                receivedAt: iter.receivedAt,
                is_final: iter.is_final,
                error: iter.error,
                messages_sent: iter.messages_sent,
                raw_response: iter.raw_response,
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
 * Exposed for Phase 11's delete feature.
 */
export async function deleteTrace(traceId) {
    return idb.execute((db) => {
        if (!db) return;
        if (!db.objectStoreNames.contains(STORE)) return;
        return new Promise((resolve, reject) => {
            const tx = db.transaction(STORE, "readwrite");
            tx.objectStore(STORE).delete(traceId);
            tx.oncomplete = resolve;
            tx.onerror = () => reject(tx.error);
            tx.commit();
        });
    });
}

/**
 * Load all stored traces from IndexedDB.
 * Returns an array of plain serialized trace records.
 * Returns [] if IDB is unavailable or store is empty.
 *
 * Note: records contain iterations as [iterId, iterRecord] pair arrays
 * and dates as ISO strings — hydrateTrace() in app.js reconstructs the
 * reactive Maps and Date objects.
 */
export async function loadAllTraces() {
    return idb.execute((db) => {
        if (!db) return [];
        if (!db.objectStoreNames.contains(STORE)) return [];
        return new Promise((resolve, reject) => {
            const tx = db.transaction(STORE, "readonly");
            const req = tx.objectStore(STORE).getAll();
            req.onsuccess = () => resolve(req.result ?? []);
            tx.onerror = () => reject(tx.error);
        });
    });
}
