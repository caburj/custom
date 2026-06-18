/** @odoo-module **/

import { describe, expect, test } from "@odoo/hoot";
import { AiDebugStore } from "@ai_debug/store";

const FIELDS_PER_MODEL = {
    "ai.debug.thread": {
        id: { type: "integer" },
        session_id: { type: "char" },
        agent_id: { type: "many2one", relation: "ai.agent" },
        user_id: { type: "many2one", relation: "res.users" },
        parent_thread_id: { type: "many2one", relation: "ai.debug.thread" },
        loop_count: { type: "integer" },
        loop_ids: { type: "one2many", relation: "ai.debug.loop" },
    },
    "ai.debug.loop": {
        id: { type: "integer" },
        thread_id: { type: "many2one", relation: "ai.debug.thread" },
        parent_tool_call_id: { type: "many2one", relation: "ai.debug.tool.call" },
    },
    "ai.debug.iteration": {
        id: { type: "integer" },
        loop_id: { type: "many2one", relation: "ai.debug.loop" },
        sequence: { type: "integer" },
        available_tool_ids: { type: "many2many", relation: "ir.actions.server" },
    },
    "ai.debug.tool.call": {
        id: { type: "integer" },
        iteration_id: { type: "many2one", relation: "ai.debug.iteration" },
        tool_id: { type: "many2one", relation: "ir.actions.server" },
    },
    "ir.actions.server": {
        id: { type: "integer" },
        display_name: { type: "char" },
        llm_name: { type: "char" },
    },
};

function makeStoreWithSchema() {
    const store = new AiDebugStore();
    for (const [model, fields] of Object.entries(FIELDS_PER_MODEL)) {
        store.registerModel(model, fields, model === "ai.debug.thread" ? "-id" : "id");
    }
    return store;
}

const SAMPLE_BUNDLE = {
    schema_version: 1,
    exported_at: "2026-05-05T00:00:00+00:00",
    source_db: "test-db",
    root_thread_id: 42,
    threads: [{
        id: 42,
        session_id: "s-1",
        agent_id: [7, "Test Agent"],
        user_id: [1, "admin"],
        parent_thread_id: false,
        loop_count: 1,
    }],
    loops: [{ id: 100, thread_id: [42, ""], parent_tool_call_id: false }],
    iterations: [{ id: 200, loop_id: [100, ""], sequence: 0, available_tool_ids: [9] }],
    tool_calls: [{ id: 300, iteration_id: [200, ""], tool_id: [9, "search_records"] }],
    tools: [{ id: 9, display_name: "Search Records", llm_name: "search_records" }],
};

describe("loadFromImport", () => {
    test("flips isImported and stores meta", async () => {
        const store = makeStoreWithSchema();
        await store.loadFromImport(SAMPLE_BUNDLE);
        expect(store.isImported()).toBe(true);
        expect(store.importMeta()).toEqual({
            exported_at: "2026-05-05T00:00:00+00:00",
            source_db: "test-db",
            root_thread_id: 42,
        });
    });

    test("populates all four record buckets + ir.actions.server", async () => {
        const store = makeStoreWithSchema();
        await store.loadFromImport(SAMPLE_BUNDLE);
        // Use Boolean checks to avoid passing Record proxies to the Hoot formatter
        expect(store.get("ai.debug.thread", 42) !== null).toBe(true);
        expect(store.get("ai.debug.loop", 100) !== null).toBe(true);
        expect(store.get("ai.debug.iteration", 200) !== null).toBe(true);
        expect(store.get("ai.debug.tool.call", 300) !== null).toBe(true);
        expect(store.get("ir.actions.server", 9) !== null).toBe(true);
    });

    test("marks thread list and per-thread state as fully loaded", async () => {
        const store = makeStoreWithSchema();
        await store.loadFromImport(SAMPLE_BUNDLE);
        expect(store.threadListFullyLoaded).toBe(true);
        expect(store.isFullyLoaded(42)).toBe(true);
    });

    test("auto-selects the root thread", async () => {
        const store = makeStoreWithSchema();
        await store.loadFromImport(SAMPLE_BUNDLE);
        expect(store.selectedThreadId()).toBe(42);
    });

    test("clearAll wipes records and flips isImported off", async () => {
        const store = makeStoreWithSchema();
        await store.loadFromImport(SAMPLE_BUNDLE);
        store.clearAll();
        expect(store.isImported()).toBe(false);
        expect(store.get("ai.debug.thread", 42)).toBe(null);
        expect(store.selectedThreadId()).toBe(null);
    });
});

describe("boot-chain race", () => {
    /**
     * A click on Import while ``loadFromServer``'s ``fields_get`` RPC is
     * still in flight used to either crash (``insert`` into undefined
     * record bucket) or silently wipe the imported records (``registerModel``
     * resets ``this.records[name] = {}``). ``loadFromImport`` now awaits
     * the cached init promise, and ``loadFromServer`` skips registerModel
     * if it resumes after import. This test pins both halves down.
     */
    test("loadFromImport waits for in-flight loadFromServer", async () => {
        const store = new AiDebugStore();
        let resolveFieldsGet;
        const fieldsGetGate = new Promise((resolve) => {
            resolveFieldsGet = resolve;
        });
        const orm = {
            call: (model, method) => {
                expect(method).toBe("fields_get");
                return fieldsGetGate.then(() => FIELDS_PER_MODEL[model]);
            },
        };
        // Kick off init but don't let fields_get resolve yet.
        const initPromise = store.loadFromServer(orm);
        // User clicks Import while init is still in flight.
        const importPromise = store.loadFromImport(SAMPLE_BUNDLE);
        // The import shouldn't have populated buckets yet -- it must
        // wait for schemas first.
        expect(store.isImported()).toBe(false);
        // Resolve fields_get; both promises now make progress.
        resolveFieldsGet();
        await initPromise;
        await importPromise;
        // Imported records survive; registerModel didn't wipe them.
        expect(store.isImported()).toBe(true);
        expect(store.get("ai.debug.thread", 42) !== null).toBe(true);
        expect(store.selectedThreadId()).toBe(42);
    });

    test("fetchThreads bails after import flips mid-flight", async () => {
        const store = makeStoreWithSchema();
        let resolveFetch;
        const fetchGate = new Promise((resolve) => {
            resolveFetch = resolve;
        });
        const orm = {
            call: () => fetchGate.then(() => ({
                threads: [{
                    id: 999,
                    session_id: "live",
                    agent_id: [1, "Live Agent"],
                    user_id: [1, "admin"],
                    parent_thread_id: false,
                    loop_count: 0,
                }],
                total: 1,
            })),
        };
        // Kick off a live fetch but don't resolve it yet.
        const fetchPromise = store.fetchThreads(orm, { limit: 10 });
        // Import happens while the fetch is in flight.
        await store.loadFromImport(SAMPLE_BUNDLE);
        // Now resolve the live fetch -- it should not insert thread 999.
        resolveFetch();
        await fetchPromise;
        expect(store.get("ai.debug.thread", 999)).toBe(null);
        expect(store.get("ai.debug.thread", 42) !== null).toBe(true);
    });
});

describe("bus gating", () => {
    test("guard helper short-circuits when isImported is true", async () => {
        const store = makeStoreWithSchema();
        await store.loadFromImport(SAMPLE_BUNDLE);
        let called = 0;
        const guarded = (handler) => (payload) => {
            if (store.isImported()) return;
            called++;
            handler(payload);
        };
        const handler = guarded(() => {});
        handler({ id: 999 });
        expect(called).toBe(0);

        store.clearAll();
        handler({ id: 999 });
        expect(called).toBe(1);
    });
});
