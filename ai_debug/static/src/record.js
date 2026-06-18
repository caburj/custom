/** @odoo-module **/

import { signal } from "@odoo/owl";
import { LAZY_FIELDS } from "./lazy_fields";

export const RAW = Symbol("raw");
export const NAMES = Symbol("names");
export const MODEL = Symbol("model");
const STORE = Symbol("store");
const SIGS = Symbol("sigs");

/**
 * Proxy-based record with OWL 3 signal-backed reactivity.
 *
 * Each scalar field is backed by a per-field signal, materialized lazily
 * on the first read. Reads through the proxy's ``get`` trap subscribe the
 * caller to that signal; writes through the ``set`` trap update both the
 * raw value AND notify the signal so subscribers re-render.
 *
 * Relation fields route through the store's ``signal.Object`` buckets and
 * ``lazyState`` so insertions / lazy-state flips notify subscribers too:
 *
 *   - many2one: ``store.records[meta.relation]()[id]`` — bucket read
 *     subscribes; when the related Record arrives, the consumer re-renders.
 *   - one2many: ``store.getBy(...)`` — getBy iterates the bucket via
 *     ``signal.Object`` (subscribes), so child inserts notify.
 *   - many2many (lazy): bucket read + ``store.lazyState()`` read — wires
 *     up to both record loads and loading-flag flips.
 *
 * Identity invariant: the Proxy returned from ``new Record(...)`` is
 * stable for the lifetime of a ``(model, id)`` pair. ``store.update``
 * writes through this same proxy's ``set`` trap; ``store.upsert`` returns
 * the existing instance. Components that capture a Record in a closure
 * keep the same handle and their per-field signal subscriptions stay
 * wired across re-renders.
 */
export class Record {
    constructor(store, model, raw, names = {}) {
        this[RAW] = raw;
        this[STORE] = store;
        this[MODEL] = model;
        this[NAMES] = names;
        // Per-field signals: created lazily on first read of a scalar field
        // so we don't materialize signals for fields no component touches.
        this[SIGS] = {};
        return new Proxy(this, RECORD_TRAP);
    }
}

const RECORD_TRAP = {
    get(target, prop) {
        // Symbols (RAW, NAMES, etc.) and OWL internals: direct access.
        if (typeof prop === "symbol") {
            return target[prop];
        }

        // Expose store so consumers (and tests) can reach it.
        if (prop === "__store") {
            return target[STORE];
        }

        const store = target[STORE];
        const meta = store.fields[target[MODEL]]?.[prop];

        if (meta?.type === "many2one") {
            const id = target[RAW][prop];
            if (!id) return null;
            // Internal model: resolve to the full Record if loaded.
            // Reading through ``store.records[meta.relation]()`` subscribes
            // to the signal.Object bucket — when the related Record arrives
            // (e.g. via a fetch_loops_through race or live bus push), the
            // subscriber re-renders.
            // Fall back to {id, name} stub if the record hasn't been loaded
            // yet (e.g. a loop's parent_tool_call_id whose tool call record
            // lives in a different thread that isn't currently open).
            if (store.hasModel(meta.relation)) {
                const record = store.records[meta.relation]()[id];
                if (record) return record;
            }
            // Stub with cached display name from search_read's [id, name].
            return { id, name: target[NAMES][prop] || "" };
        }

        if (meta?.type === "one2many") {
            // store.getBy reads through the signal.Object bucket, so
            // subscriptions wire up at the call site automatically: when
            // a child record is inserted into the bucket, OWL re-renders.
            return store.getBy(meta.relation, meta.relation_field, target[RAW].id);
        }

        if (meta?.type === "many2many") {
            // m2m values arrive from the server as plain arrays of ids.
            //
            // For fields registered in LAZY_FIELDS we emit typed entries
            // (``{id, state, record}``) so the component can render a
            // placeholder while a batched ``search_read`` resolves the
            // related rows. Reads of ``store.records[meta.relation]()``
            // subscribe to the bucket; reading ``store.lazyState()`` also
            // subscribes to loading-flag flips.
            //
            // For fields NOT in LAZY_FIELDS we return a flat array of
            // resolved Records (missing ids silently dropped).
            const ids = target[RAW][prop] || [];
            const lazyCfg = LAZY_FIELDS[target[MODEL]]?.[prop];
            const bucket = store.records[meta.relation]?.() || {};
            if (lazyCfg) {
                const lazyMap = store.lazyState();  // subscribe
                const lazyModelState = lazyMap[meta.relation];
                return ids.map((id) => {
                    const record = bucket[id];
                    if (record) return { id, state: "loaded", record };
                    const s = lazyModelState?.[id];
                    if (s === "loading") return { id, state: "loading", record: null };
                    if (s === "loaded-null") return { id, state: "loaded", record: null };
                    return { id, state: "missing", record: null };
                });
            }
            const records = [];
            for (const id of ids) {
                const rec = bucket[id];
                if (rec) records.push(rec);
            }
            return records;
        }

        // Scalar field: lazily create a per-field signal initialized with
        // the current raw value. The read subscribes; subsequent writes via
        // the set trap call .set on the same signal so all subscribers fire.
        //
        // Materialize + subscribe even when the field is ABSENT from raw, as
        // long as it's a genuine data field (declared in the model schema, or
        // already present in raw). The live recorder inserts a partial row and
        // fills the heavy body later via ``store.update`` (e.g. an iteration's
        // raw_response / a tool call's result / a loop's input_message). A
        // reader that touched the field while it was still absent — typically a
        // PARENT computing a scalar prop for a child (``content="loop.input_message"``,
        // ``data="iteration.raw_response"``) — must subscribe NOW, so the later
        // ``set`` notifies it, the parent re-renders, and the computed prop is
        // re-passed. Without this the parent never subscribes and the child is
        // stuck on the stale ``undefined`` ("No message" / blank tab).
        if (meta || prop in target[RAW]) {
            let sig = target[SIGS][prop];
            if (!sig) {
                sig = signal(target[RAW][prop]);
                target[SIGS][prop] = sig;
            }
            return sig();
        }

        // Non-data keys (constructor, prototype methods, framework probes like
        // ``then``): fall back to the real instance property — no signal wrap.
        return target[prop];
    },

    set(target, prop, value) {
        if (typeof prop === "symbol") {
            target[prop] = value;
            return true;
        }
        // Write to _raw (single source of truth) and notify subscribers via
        // the per-field signal. If no read ever happened (no signal yet),
        // create one so a later read sees the up-to-date value through the
        // signal-cached path.
        target[RAW][prop] = value;
        let sig = target[SIGS][prop];
        if (!sig) {
            sig = signal(value);
            target[SIGS][prop] = sig;
        } else {
            sig.set(value);
        }
        return true;
    },
};
