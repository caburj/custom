/** @odoo-module **/
import { sortBy } from "@web/core/utils/arrays";
import { computed, Plugin, signal } from "@odoo/owl";
import { Record, RAW, NAMES, MODEL } from "./record";
import { LAZY_FIELDS } from "./lazy_fields";

const MODELS = [
    { name: "ai.debug.thread", order: "-id" },
    { name: "ai.debug.loop", order: "id" },
    { name: "ai.debug.iteration", order: "sequence" },
    { name: "ai.debug.tool.call", order: "id" },
    // ir.actions.server records ship lazily via ``ensureRelated`` when the
    // "Available Tools" tab is opened on an iteration -- we keep the bucket
    // registered so loaded rows have a home and repeated opens hit the cache.
    { name: "ir.actions.server", order: "id" },
];

export class AiDebugStore extends Plugin {
    // -- Schema (plain objects; populated by registerModel) ---------------
    /** @type {Object<string, Object>} model -> fields_get result */
    fields = {};
    /** @type {Object<string, string>} model -> sort field (prefix "-" for desc) */
    order = {};

    // -- Record buckets: signal.Object so insert/delete notify ------------
    /** @type {Object<string, ReturnType<typeof signal.Object>>} */
    records = {
        "ai.debug.thread": signal.Object({}),
        "ai.debug.loop": signal.Object({}),
        "ai.debug.iteration": signal.Object({}),
        "ai.debug.tool.call": signal.Object({}),
        "ir.actions.server": signal.Object({}),
    };

    // -- Scalar reactive state as signals --------------------------------
    /** Total thread count from the server (shown in sidebar header). */
    threadCount = signal(0);
    /** Currently selected thread id (null if none). */
    selectedThreadId = signal(null);
    /**
     * Cross-component focus signal for "jump to a specific tool call".
     * Components watch [focusToolCallId, focusNonce]: the nonce bumps on
     * every request so re-clicking the same target retriggers effects.
     * Fired by a child thread's user-bubble back-link in the conversation
     * view; consumed by LoopDetailStrip / IterationSection (auto-expand)
     * and ToolCallCard (scroll-to-center).
     */
    focusToolCallId = signal(null);
    /**
     * Companion focus signal for "jump to a specific loop". Fired by a
     * tool-call card's child-loop badge (when the call drove a subagent
     * loop). Consumed by LoopDetailStrip (scroll-to-center).
     */
    focusLoopId = signal(null);
    focusNonce = signal(0);
    /**
     * True while a focus-jump is in flight -- from focusToolCall()
     * entry until the target card's visibility observer fires (or
     * its safety timer). ConversationView's sentinel _fetchMoreLoops
     * checks this flag and bails, so a smooth-scroll that crosses
     * the top sentinel can't trigger a loop fetch that shifts the
     * target's Y and throws off the scroll landing.
     */
    isFocusing = signal(false);
    /**
     * True when the store is showing an imported transcript instead of
     * live data. Set by ``loadFromImport``; cleared by ``clearAll`` or a
     * page reload. Bus subscriptions in app.js gate on this flag so
     * incoming live events don't corrupt the imported view.
     */
    isImported = signal(false);
    /**
     * Provenance metadata for the currently-loaded imported trace.
     * Drives the "Viewing imported trace" banner. Null in live mode.
     * Holds { exported_at, source_db, root_thread_id } | null.
     */
    importMeta = signal(null);
    /**
     * Wall-clock tick in epoch ms, updated once per second by AiDebugApp's
     * ticker. Read by ThreadTreeItem only when it has a running loop, so
     * idle rows don't subscribe and don't re-render on each tick.
     */
    now = signal(Date.now());

    // -- Signal-backed maps ----------------------------------------------
    /**
     * Thread ids whose sidebar row has its children hidden. Stored as a
     * signal.Object keyed by id (value always true) so Owl tracks reads.
     * Absence from this map = expanded, which is the default for every
     * thread. Mutated by sidebar row toggle, auto-expand-on-selection,
     * and the header "collapse all / expand all" button.
     */
    collapsedThreadIds = signal.Object({});

    // -- Lazy m2m loading -----------------------------------------------
    //
    // Every lazy entry is in exactly one of three states:
    //   - missing      -> never requested; no presence in ``lazyState``
    //                     and no Record in the bucket.
    //   - loading      -> ``lazyState()[model][id] === "loading"``
    //   - loaded       -> Record in the bucket, OR
    //                     ``lazyState()[model][id] === "loaded-null"``.
    /** @type {ReturnType<typeof signal.Object>} */
    lazyState = signal.Object({});

    /**
     * Per-thread loop pagination state, keyed by thread id:
     * ``{ [threadId]: { loading, fullyLoaded } }``. signal.Object so the
     * sentinel ``t-if`` and spinner ``t-if`` in ConversationView toggle
     * reactively as loops are fetched in.
     */
    _threadLoading = signal.Object({});
    /**
     * Thread-list pagination state: ``{ loading, fullyLoaded }``. signal.Object
     * so the sidebar's sentinel and spinner toggle reactively.
     */
    _threadListState = signal.Object({ loading: false, fullyLoaded: false });

    // -- Non-reactive internal state (no subscribers needed) ------------
    /** @type {Object<string, Set<number>>} */
    _lazyPending = {};
    /** @type {Object<string, Set<number>>} */
    _lazyInFlight = {};
    /** @type {Object<string, boolean>} */
    _lazyScheduled = {};
    /**
     * Promise that resolves once ``loadFromServer`` has registered the
     * model schemas. ``loadFromImport`` awaits this so a fast Import
     * click during boot doesn't try to ``insert`` into undefined
     * record buckets, and so async live fetches that resume after
     * import can short-circuit on ``isImported``.
     * @type {Promise<void> | null}
     */
    _initPromise = null;
    /** ORM service; set via ``init(orm)`` once the store is mounted. */
    orm = null;

    /** Stash the orm service so lazy loaders can issue RPCs without it being threaded through. */
    init(orm) {
        this.orm = orm;
    }

    // -- Sidebar thread-tree expand/collapse ----------------------------

    isThreadCollapsed(threadId) {
        return Boolean(this.collapsedThreadIds()[threadId]);
    }

    setThreadCollapsed(threadId, collapsed) {
        const m = this.collapsedThreadIds();
        if (collapsed) {
            m[threadId] = true;
        } else {
            delete m[threadId];
        }
    }

    /** Collapse every thread in the forest that has children. */
    collapseAllThreads(rootThreads) {
        const m = this.collapsedThreadIds();
        const walk = (thread) => {
            if ((thread.child_thread_ids?.length || 0) === 0) return;
            m[thread.id] = true;
            for (const child of thread.child_thread_ids) walk(child);
        };
        for (const thread of rootThreads) walk(thread);
    }

    /** Expand every thread (clears all collapsed state). */
    expandAllThreads() {
        this.collapsedThreadIds.set({});
    }

    /**
     * Apply the default-fold rule to a freshly-loaded/pushed thread.
     *
     * Roots start folded. Children start folded iff their parent is
     * currently folded (or its parent hasn't arrived yet — covers the
     * initial fetch batch where descendants can stream in alongside
     * their parents). Children under an already-expanded parent stay
     * expanded so live sub-agent activity streams in without a click.
     *
     * No-op if the thread already has an explicit collapse state — never
     * overrides a user's manual expand.
     *
     * Accepts the raw payload (many2one as [id, name] tuple from
     * search_read, or a plain id from bus push).
     */
    applyDefaultCollapse(thread) {
        const m = this.collapsedThreadIds();
        if (thread.id in m) return;
        const parentRaw = thread.parent_thread_id;
        const parentId = Array.isArray(parentRaw) ? parentRaw[0] : parentRaw || null;
        if (!parentId
            || !this.get("ai.debug.thread", parentId)
            || this.isThreadCollapsed(parentId)) {
            m[thread.id] = true;
        }
    }

    // -- Schema ---------------------------------------------------------

    /**
     * Register a model's field metadata. The reactive bucket already exists
     * (initialized as a class field above); we don't reset it here so that
     * imported records inserted before fields_get returns aren't wiped.
     */
    registerModel(model, fieldsGet, order) {
        this.fields[model] = fieldsGet;
        this.order[model] = order;
    }

    /** Check whether a model is registered (i.e. its records live in this store). */
    hasModel(model) {
        return model in this.fields;
    }

    // -- Lookups --------------------------------------------------------

    /** Get a single record by model + id. Returns Record or null. */
    get(model, id) {
        const bucket = this.records[model];
        return bucket ? bucket()[id] || null : null;
    }

    /**
     * Get all records of `model` where `field === value`.
     * Returns a sorted array of Records.
     */
    getBy(model, field, value) {
        const bucket = this.records[model];
        if (!bucket) return [];
        const result = [];
        for (const record of Object.values(bucket())) {
            if (record[RAW][field] === value) {
                result.push(record);
            }
        }
        return this._sort(model, result);
    }

    /** Get all records of a model, sorted by the model's default order. */
    getAll(model) {
        const bucket = this.records[model];
        if (!bucket) return [];
        return this._sort(model, Object.values(bucket()));
    }

    /** Get all root threads (no parent_thread_id), sorted newest-first. */
    getRootThreads() {
        const bucket = this.records["ai.debug.thread"];
        if (!bucket) return [];
        const roots = [];
        for (const record of Object.values(bucket())) {
            if (!record[RAW].parent_thread_id) {
                roots.push(record);
            }
        }
        return this._sort("ai.debug.thread", roots);
    }

    /** Memoized computed used by ThreadSidebar to render the forest. */
    rootThreads = computed(() => this.getRootThreads());

    // -- Mutations ------------------------------------------------------

    /**
     * Insert a new record. Normalizes Many2one values ([id, name] tuples
     * from search_read are split into raw ID + cached display name).
     */
    insert(model, vals) {
        const { raw, names } = this._normalizeVals(model, vals);
        const record = new Record(this, model, raw, names);
        // Proxied object: writes to keys notify subscribers.
        const bucket = this.records[model]();
        bucket[raw.id] = record;
        return record;
    }

    /**
     * Insert only if no record with this id exists yet. Returns the
     * existing record otherwise. Used by the lazy-load batcher: repeated
     * resolution calls for the same id must not churn Record proxies, so
     * OWL identity stays stable for any holder that captured the record.
     */
    upsert(model, vals) {
        const existing = this.get(model, vals.id);
        if (existing) return existing;
        return this.insert(model, vals);
    }

    /**
     * Update an existing record's fields. Merges via OWL-wrapped set.
     */
    update(model, id, vals) {
        const record = this.get(model, id);
        if (!record) return;
        const { raw, names } = this._normalizeVals(model, vals);
        for (const [key, value] of Object.entries(raw)) {
            if (key === "id") continue;
            record[key] = value;
        }
        for (const [key, value] of Object.entries(names)) {
            record[NAMES][key] = value;
        }
    }

    // -- Init -----------------------------------------------------------

    /**
     * Load field metadata (fields_get) for all models.
     * Threads and loops are loaded on demand via fetchThreads() / fetchLoops().
     */
    async loadFromServer(orm) {
        if (this._initPromise) return this._initPromise;
        this._initPromise = (async () => {
            const fieldsGetResults = await Promise.all(
                MODELS.map(({ name }) => orm.call(name, "fields_get"))
            );
            // If the user clicked Import while fields_get was in flight,
            // ``isImported`` is now true and ``loadFromImport`` already
            // populated the buckets. Don't wipe them via registerModel.
            if (this.isImported()) return;
            MODELS.forEach(({ name, order }, i) =>
                this.registerModel(name, fieldsGetResults[i], order)
            );
        })();
        return this._initPromise;
    }

    // -- Internal -------------------------------------------------------

    /**
     * Normalize vals for storage. Many2one [id, name] tuples from search_read
     * are split: ID goes into raw, display name goes into names.
     */
    _normalizeVals(model, vals) {
        const schema = this.fields[model];
        if (!schema) return { raw: { ...vals }, names: {} };

        const raw = {};
        const names = {};
        for (const [field, value] of Object.entries(vals)) {
            const meta = schema[field];
            if (meta?.type === "one2many") {
                continue; // derived from the inverse many2one, never stored
            }
            if (meta?.type === "many2one") {
                if (Array.isArray(value)) {
                    raw[field] = value[0];
                    names[field] = value[1] || "";
                } else {
                    raw[field] = value || null;
                }
            } else {
                raw[field] = value;
            }
        }
        return { raw, names };
    }

    _sort(model, records) {
        const order = this.order[model] || "id";
        const desc = order.startsWith("-");
        const field = desc ? order.slice(1) : order;
        return sortBy(records, (r) => r[RAW][field] ?? 0, desc ? "desc" : "asc");
    }

    // -- Lazy m2m loading -----------------------------------------------

    /**
     * Queue *ids* on *model* for a batched ``search_read`` with *fields*.
     *
     * The first id on a given model in a microtask triggers a scheduled
     * flush; subsequent calls within the same microtask coalesce their ids
     * into the same batch. Already-loaded ids (present in the bucket) and
     * ids currently in flight are skipped -- ``ensureRelated`` is cheap to
     * call repeatedly (once per component mount + tab switch).
     */
    ensureRelated(model, fields, ids) {
        if (!ids || ids.length === 0) return;
        const bucket = this.records[model]?.() || {};
        const lazyMap = this.lazyState();
        const lazyModelState = lazyMap[model] || {};
        const inFlight = this._lazyInFlight[model];
        let pending = this._lazyPending[model];
        for (const id of ids) {
            if (bucket[id]) continue;
            if (inFlight?.has(id)) continue;
            if (lazyModelState[id] === "loaded-null") continue;
            if (lazyModelState[id] === "loading") continue;
            if (!pending) {
                pending = new Set();
                this._lazyPending[model] = pending;
            }
            pending.add(id);
            if (!lazyMap[model]) lazyMap[model] = {};
            lazyMap[model][id] = "loading";
        }
        if (pending && pending.size && !this._lazyScheduled[model]) {
            this._lazyScheduled[model] = true;
            queueMicrotask(() => this._flushPending(model, fields));
        }
    }

    /**
     * Pull this iteration's/field's lazy config off ``LAZY_FIELDS`` and
     * schedule a fetch for the ids currently on *record*. Intended to be
     * called from a component ``useEffect`` gated on tab activation.
     */
    ensureLazyField(record, fieldName) {
        if (!record) return;
        const model = record[MODEL];
        const config = LAZY_FIELDS[model]?.[fieldName];
        if (!config) return;
        const ids = record[RAW][fieldName] || [];
        this.ensureRelated(config.relation, config.fields, ids);
    }

    async _flushPending(model, fields) {
        const pending = this._lazyPending[model];
        if (!pending || pending.size === 0) {
            this._lazyScheduled[model] = false;
            return;
        }
        const inFlight = pending;
        this._lazyPending[model] = new Set();
        this._lazyInFlight[model] = inFlight;
        this._lazyScheduled[model] = false;

        const ids = [...inFlight];
        const lazyMap = this.lazyState();
        if (!this.orm) {
            // Shouldn't happen in the mounted app (init runs before any
            // iteration is rendered), but guard so a missing wire-up fails
            // gracefully rather than raising inside the microtask.
            for (const id of ids) {
                lazyMap[model][id] = "loaded-null";
            }
            this._lazyInFlight[model] = new Set();
            return;
        }
        try {
            const rows = await this.orm.call(model, "search_read", [], {
                domain: [["id", "in", ids]],
                fields,
            });
            const returnedIds = new Set();
            for (const row of rows) {
                returnedIds.add(row.id);
                this.upsert(model, row);
                delete lazyMap[model][row.id];
            }
            for (const id of ids) {
                if (!returnedIds.has(id)) {
                    lazyMap[model][id] = "loaded-null";
                }
            }
        } catch {
            // RPC failed: clear the "loading" flag so a subsequent tab-open
            // retries instead of staying stuck on the spinner forever.
            for (const id of ids) delete lazyMap[model][id];
        } finally {
            this._lazyInFlight[model] = new Set();
        }

        // If new ids were queued while we were awaiting the RPC, flush again.
        if (this._lazyPending[model]?.size && !this._lazyScheduled[model]) {
            this._lazyScheduled[model] = true;
            queueMicrotask(() => this._flushPending(model, fields));
        }
    }

    // -- Thread-list pagination ------------------------------------------

    /** Whether the thread list is currently fetching a page. */
    get threadListLoading() {
        return this._threadListState().loading;
    }

    /** Whether all threads have been loaded. */
    get threadListFullyLoaded() {
        return this._threadListState().fullyLoaded;
    }

    /**
     * Fetch a page of threads from the server.
     *
     * @param {Object} orm
     * @param {Object} opts
     * @param {number} [opts.limit=10] - page size
     * @returns {Promise<void>}
     */
    async fetchThreads(orm, { limit = 10 } = {}) {
        // signal.Object proxy: mutations via this handle notify subscribers.
        const state = this._threadListState();
        if (state.loading || state.fullyLoaded) return;
        // Race guard: the ThreadSidebar's IntersectionObserver fires on mount
        // with an empty list (sentinel immediately in view), which can trigger
        // _fetchOlderThreads before loadFromServer has finished registering
        // model buckets. Silently bail; the app's own post-loadFromServer
        // fetchThreads call (see AiDebugApp.setup) will run once the store is
        // ready and patch-driven observer reconnects pick up from there.
        if (!this.hasModel("ai.debug.thread")) return;

        // Cursor: the oldest currently loaded root thread. Pagination is on
        // roots only (the server also returns their descendants, but those
        // don't count toward the limit).
        const roots = this.getRootThreads();
        const beforeId = roots.length ? roots[roots.length - 1].id : null;

        state.loading = true;
        try {
            const result = await orm.call(
                "ai.debug.thread", "fetch_threads", [], { before_id: beforeId, limit }
            );
            // A user can click Import while this RPC is in flight; the
            // entry state-check ran before the await so we re-check
            // here to avoid mixing live records into the imported view.
            if (this.isImported()) return;
            for (const t of result.threads) {
                this.insert("ai.debug.thread", t);
                this.applyDefaultCollapse(t);
            }
            // Subagent loop stubs ({id, thread_id, parent_tool_call_id,
            // model_name}) so parent tool calls can render "↗ <agent>" badges
            // before the user navigates into the subagent thread.
            for (const l of result.subagent_loops || []) {
                this.upsert("ai.debug.loop", l);
            }
            this.threadCount.set(result.total);
            // Only root threads count toward pagination; descendants come
            // along for the ride but aren't part of the page size.
            const rootsReturned = result.threads.filter((t) => !t.parent_thread_id).length;
            if (rootsReturned < limit) {
                state.fullyLoaded = true;
            }
        } finally {
            state.loading = false;
        }
    }

    // -- Loop pagination -------------------------------------------------

    /**
     * Get or create loading state for a thread.
     *
     * Returns a small handle whose ``loading`` / ``fullyLoaded`` setters
     * write a fresh object back into the ``_threadLoading`` signal.Object
     * proxy. signal.Object is shallow, so mutating a nested entry
     * in-place wouldn't notify subscribers — we replace the entry instead.
     */
    _getThreadState(threadId) {
        const map = this._threadLoading();
        if (!map[threadId]) {
            map[threadId] = {
                loading: false,
                fullyLoaded: false,
                // initialFetched is separate from loop_ids.length because
                // fetchThreads pre-populates partial loop stubs (id +
                // thread_id + parent_tool_call_id) for subagent threads so
                // parent tool-call cards can render their child-loop badges
                // before the user navigates in. Those stubs make
                // ``thread.loop_ids`` non-empty, but the loops still need a
                // full fetch (iterations, tool calls, message bodies) the
                // first time their thread is opened. ``_fetchMoreLoops``
                // gates on this flag instead of ``loop_ids.length``.
                initialFetched: false,
            };
        }
        const self = this;
        return {
            get loading() { return self._threadLoading()[threadId].loading; },
            set loading(v) {
                const m = self._threadLoading();
                m[threadId] = { ...m[threadId], loading: v };
            },
            get fullyLoaded() { return self._threadLoading()[threadId].fullyLoaded; },
            set fullyLoaded(v) {
                const m = self._threadLoading();
                m[threadId] = { ...m[threadId], fullyLoaded: v };
            },
            get initialFetched() { return self._threadLoading()[threadId].initialFetched; },
            set initialFetched(v) {
                const m = self._threadLoading();
                m[threadId] = { ...m[threadId], initialFetched: v };
            },
        };
    }

    /** Whether a fetch is in progress for this thread. */
    isLoading(threadId) {
        return this._threadLoading()[threadId]?.loading || false;
    }

    /** Whether all loops for this thread have been loaded. */
    isFullyLoaded(threadId) {
        return this._threadLoading()[threadId]?.fullyLoaded || false;
    }

    /** Whether the first full fetch has completed for this thread. False if
        only ``fetchThreads`` stubs are in the bucket (or nothing at all). */
    hasInitialFetch(threadId) {
        return this._threadLoading()[threadId]?.initialFetched || false;
    }

    /**
     * Set the currently selected thread. The conversation view watches
     * ``props.thread.id`` and triggers the initial fetch via a useEffect
     * (sentinel observer alone is unreliable: ``onMounted`` scrolls to
     * bottom and the view is reused across thread switches, so the
     * observer doesn't re-fire).
     */
    selectThread(threadId) {
        this.selectedThreadId.set(threadId);
    }

    /**
     * Switch to `threadId` (loading its loops if needed) and signal that
     * `toolCallId` should be brought into focus. Watching components
     * react in setup-time useEffects keyed on [focusToolCallId, focusNonce].
     *
     * The nonce increments on every call so that focusing the same tool
     * call twice in a row still re-triggers the scroll.
     *
     * If the target tool call isn't in the store yet (either the thread
     * was never opened, or pagination hasn't reached the target's loop),
     * fetch_loops_through pulls the target loop plus any intermediate
     * loops between it and the currently-loaded oldest, so the conversation
     * view stays contiguous. The conversation's sentinel observer may
     * also fire on mount and fetch the last page in parallel; both
     * inserts are idempotent.
     */
    async focusToolCall(orm, threadId, toolCallId) {
        this.isFocusing.set(true);
        if (this.selectedThreadId() !== threadId) {
            this.selectThread(threadId);
        }
        if (!this.get("ai.debug.tool.call", toolCallId)) {
            await this._bridgeLoopGap(
                orm, threadId, "fetch_loops_through",
                { tool_call_id: toolCallId },
            );
        }
        this.focusToolCallId.set(toolCallId);
        this.focusNonce.set(this.focusNonce() + 1);
    }

    /**
     * Switch to `threadId` and signal that `loopId` should be brought into
     * focus. Used when jumping from a parent's tool-call card into the
     * specific child subagent loop that call drove. Mirrors
     * ``focusToolCall`` but anchors on a loop -- needed because the
     * target loop may have no tool calls (e.g. a synthetic confirmation
     * follow-up).
     *
     * Components watch [focusToolCallId, focusNonce] for tool-call jumps
     * and [focusLoopId, focusNonce] for loop jumps. Both share the
     * ``isFocusing`` gate so the conversation sentinel doesn't paginate
     * during a smooth-scroll.
     */
    async focusLoop(orm, threadId, loopId) {
        this.isFocusing.set(true);
        if (this.selectedThreadId() !== threadId) {
            this.selectThread(threadId);
        }
        // Two-layer gate: ``fetch_threads`` pre-populates partial loop
        // stubs ({id, thread_id, parent_tool_call_id, model_name}) for
        // every loop in subagent threads so parent tool-call cards can
        // render their child-loop badges before the user navigates in.
        // A naive ``!this.get("ai.debug.loop", loopId)`` check matches
        // those stubs and skips the fetch, leaving the conversation
        // view rendering "No message" for every loop.
        //
        // Mirror the sidebar-click path: if this thread has never had
        // a full fetch, pull the last page first (also flips
        // ``initialFetched``, so the conversation view's sentinel
        // observer doesn't redundantly re-fetch after ``endFocus``).
        // Then, if the target loop is still a stub (older than the
        // top page on a long subagent thread), bridge the remaining
        // gap.
        if (!this.hasInitialFetch(threadId)) {
            await this.fetchLoops(orm, threadId, { last: 10 });
        }
        if (this._isStubLoop(loopId)) {
            await this._bridgeLoopGap(
                orm, threadId, "fetch_loops_through_loop",
                { loop_id: loopId },
            );
        }
        this.focusLoopId.set(loopId);
        this.focusNonce.set(this.focusNonce() + 1);
    }

    /**
     * True iff *loopId* is in the bucket but only as a partial stub
     * (the {id, thread_id, parent_tool_call_id, model_name} shape that
     * ``fetch_threads`` ships for subagent loops). Stubs lack the
     * conversation-rendering fields (``input_message``, ``output_message``,
     * iterations), so callers that need those treat a stub as "missing"
     * and trigger a full fetch.
     */
    _isStubLoop(loopId) {
        const loop = this.get("ai.debug.loop", loopId);
        if (!loop) return true;
        return !("input_message" in loop[RAW]);
    }

    /**
     * Shared helper: fetch the target loop plus any intermediate loops
     * between it and the oldest currently-loaded loop, then insert the
     * returned subtree into the store. Used by both focusToolCall (anchored
     * on a tool_call_id) and focusLoop (anchored on a loop_id).
     */
    async _bridgeLoopGap(orm, threadId, methodName, kwargs) {
        // Loops are id-ordered ascending, so the first one is the oldest
        // currently loaded. Pass it as the exclusive upper bound so the
        // server returns only the gap [target_loop, oldest_loaded).
        //
        // Skip stub-only entries (the partial rows ``fetch_threads`` ships
        // for subagent threads): if we used the oldest stub as the bound
        // and the target is itself a stub older than any fully-loaded
        // loop, the server's ``id < until_loop_id`` clause would exclude
        // the target itself and the bridge would return nothing.
        const loaded = this.getBy("ai.debug.loop", "thread_id", threadId)
            .filter((l) => "input_message" in l[RAW]);
        const untilLoopId = loaded.length ? loaded[0].id : null;
        const r = await orm.call(
            "ai.debug.thread", methodName,
            [], { ...kwargs, until_loop_id: untilLoopId },
        );
        for (const l of r.loops) this.insert("ai.debug.loop", l);
        for (const it of r.iterations) this.insert("ai.debug.iteration", it);
        for (const tc of r.tool_calls) this.insert("ai.debug.tool.call", tc);
        for (const ta of r.tools || []) this.insert("ir.actions.server", ta);
    }

    /**
     * Called by the target ToolCallCard once it's actually visible in
     * the viewport (i.e. the smooth-scroll has landed) -- or by its
     * safety timer if the visibility check never fires. Re-enables
     * the sentinel observer's loop-pagination fetches.
     */
    endFocus() {
        this.isFocusing.set(false);
    }

    /**
     * Fetch a batch of loops (with iterations + tool calls) for a thread.
     * Uses cursor-based pagination: loops are fetched newest-first via
     * before_id, matching the thread-list pagination pattern.
     *
     * @param {Object} orm - the ORM service
     * @param {number} threadId
     * @param {Object} opts
     * @param {number} [opts.last] - fetch the last N loops (initial load)
     * @param {number} [opts.before] - fetch N loops with IDs < this value (scroll-up)
     * @param {number} [opts.limit=10] - batch size
     * @returns {Promise<number[]>} IDs of the newly inserted loops
     */
    async fetchLoops(orm, threadId, { last, before, limit = 10 } = {}) {
        const thread = this.get("ai.debug.thread", threadId);
        if (!thread) return [];

        const state = this._getThreadState(threadId);
        if (state.loading || state.fullyLoaded) return [];

        if (!thread.loop_count) {
            state.fullyLoaded = true;
            return [];
        }

        // Determine cursor: for initial load (last) use no cursor;
        // for scroll-up use the oldest loaded loop's ID.
        let beforeId = null;
        let fetchLimit = limit;
        if (last) {
            fetchLimit = last;
        } else if (before) {
            beforeId = before;
        } else {
            return [];
        }

        state.loading = true;
        try {
            const result = await orm.call(
                "ai.debug.thread", "fetch_loops",
                [threadId], { before_id: beforeId, limit: fetchLimit },
            );
            // Same race shape as fetchThreads -- bail if Import flipped
            // the store while this RPC was in flight.
            if (this.isImported()) return [];
            for (const l of result.loops) this.insert("ai.debug.loop", l);
            for (const it of result.iterations) this.insert("ai.debug.iteration", it);
            for (const tc of result.tool_calls) this.insert("ai.debug.tool.call", tc);
            for (const ta of result.tools || []) this.insert("ir.actions.server", ta);

            if (last) {
                state.initialFetched = true;
            }
            if (result.loops.length < fetchLimit) {
                state.fullyLoaded = true;
            }

            return result.loops.map((l) => l.id);
        } finally {
            state.loading = false;
        }
    }

    /**
     * Wipe every bucket and reset pagination/selection state. Used when
     * switching into imported mode (so live records don't leak in) and
     * symmetrically when ``clearAll`` is called from a test.
     */
    clearAll() {
        for (const { name } of MODELS) {
            if (this.records[name]) this.records[name].set({});
        }
        this._threadLoading.set({});
        this._threadListState.set({ loading: false, fullyLoaded: false });
        this.threadCount.set(0);
        this.selectedThreadId.set(null);
        this.collapsedThreadIds.set({});
        this.lazyState.set({});
        this._lazyPending = {};
        this._lazyInFlight = {};
        this._lazyScheduled = {};
        this.isImported.set(false);
        this.importMeta.set(null);
    }

    /**
     * Replace store contents with an imported transcript bundle.
     *
     * The bundle shape mirrors what ``fetch_threads`` / ``fetch_loops``
     * return server-side, so the same ``insert`` path that consumes live
     * RPC responses also consumes imported records. ``ir.actions.server``
     * rows referenced by ``tool_id`` and ``available_tool_ids`` are
     * pre-populated here so the lazy-fetch path finds them in the bucket
     * and skips the (unavailable) server round-trip.
     *
     * @param {Object} bundle - parsed JSON; see ``ai.debug.thread.export_transcript``.
     */
    async loadFromImport(bundle) {
        // Wait for ``loadFromServer`` to register model schemas before we
        // try to ``insert`` records -- ``_normalizeVals`` reads
        // ``this.fields[model]`` and ``insert`` writes into
        // ``this.records[model]``, both of which are populated by
        // ``registerModel``. A fast Import click during boot would
        // otherwise crash on undefined buckets.
        if (this._initPromise) await this._initPromise;
        this.clearAll();
        this.isImported.set(true);
        this.importMeta.set({
            exported_at: bundle.exported_at,
            source_db: bundle.source_db,
            root_thread_id: bundle.root_thread_id,
        });

        for (const t of bundle.threads || []) this.insert("ai.debug.thread", t);
        for (const l of bundle.loops || []) this.insert("ai.debug.loop", l);
        for (const it of bundle.iterations || []) this.insert("ai.debug.iteration", it);
        for (const tc of bundle.tool_calls || []) this.insert("ai.debug.tool.call", tc);
        for (const ta of bundle.tools || []) this.insert("ir.actions.server", ta);

        // Pagination state: nothing more to fetch ever.
        this._threadListState.set({ loading: false, fullyLoaded: true });
        const loadingMap = this._threadLoading();
        for (const t of bundle.threads || []) {
            loadingMap[t.id] = { loading: false, fullyLoaded: true, initialFetched: true };
            this.applyDefaultCollapse(t);
        }

        const roots = (bundle.threads || []).filter((t) => !t.parent_thread_id);
        this.threadCount.set(roots.length);
        if (roots.length) {
            // Prefer the bundle's declared root; fall back to first if absent.
            const declared = bundle.root_thread_id;
            const target = roots.find((t) => t.id === declared) || roots[0];
            this.selectThread(target.id);
        }
    }
}
