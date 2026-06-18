/** @odoo-module **/

import { Component, plugin, useEffect, props, types as t } from "@odoo/owl";
import { AiDebugStore } from "@ai_debug/store";

/** Parse an Odoo datetime string (naive UTC) as epoch ms.
    Accepts both ``"2026-05-04 10:00:00"`` (search_read) and
    ``"2026-05-04T10:00:00.123456"`` (bus payload). */
function parseOdooDatetime(s) {
    if (!s) return null;
    const iso = String(s).replace(" ", "T") + "Z";
    const t = Date.parse(iso);
    return Number.isNaN(t) ? null : t;
}

/** Compact elapsed format: ``Ns`` / ``MmSSs`` / ``HhMMmSSs``. */
function formatElapsed(ms) {
    const total = Math.max(0, Math.floor(ms / 1000));
    const s = total % 60;
    const m = Math.floor(total / 60) % 60;
    const h = Math.floor(total / 3600);
    const ss = String(s).padStart(2, "0");
    if (h > 0) return `${h}h${String(m).padStart(2, "0")}m${ss}s`;
    if (m > 0) return `${m}m${ss}s`;
    return `${s}s`;
}

export class ThreadTreeItem extends Component {
    static template = "ai_debug.ThreadTreeItem";
    static components = {}; // self-reference added below
    props = props({
        thread: t.object(),
        depth: t.number(),
        selectedThreadId: t.or([t.number(), t.literal(null)]),
        onSelect: t.function(),
    });

    store = plugin(AiDebugStore);

    setup() {
        // Expand state lives in the store (keyed by thread id) so the sidebar
        // header's collapse-all / expand-all button can control every row.

        // Auto-expand when a descendant becomes selected.
        // selectedThreadId is a plain prop (not a signal) — OWL re-renders
        // when the parent passes a new value, so the effect body reads
        // this.containsSelected on every render that receives a new prop.
        useEffect(() => {
            if (this.containsSelected && !this.expanded) {
                this.store.setThreadCollapsed(this.props.thread.id, false);
            }
        });
    }

    get isSelected() {
        return this.props.selectedThreadId === this.props.thread.id;
    }

    get hasChildren() {
        return (this.props.thread.child_thread_ids?.length || 0) > 0;
    }

    /** Children in spawn order (id asc). The store sorts ``ai.debug.thread``
        ``-id`` desc -- right for the root-thread feed (newest run on top),
        wrong for sibling subagents, which should render in the order their
        parent spawned them. */
    get orderedChildren() {
        const children = this.props.thread.child_thread_ids || [];
        return [...children].sort((a, b) => a.id - b.id);
    }

    /** True if any descendant (any depth) is currently selected. */
    get containsSelected() {
        const selId = this.props.selectedThreadId;
        if (selId == null) return false;
        const walk = (t) => {
            for (const c of t.child_thread_ids || []) {
                if (c.id === selId) return true;
                if (walk(c)) return true;
            }
            return false;
        };
        return walk(this.props.thread);
    }

    get displayName() {
        const t = this.props.thread;
        // For sub-agent threads (non-root), prefer agent name over session/channel name
        if (t.parent_thread_id && t.agent_id?.name) {
            return t.agent_id.name;
        }
        return t.name || t.agent_id?.name || `Session ${t.session_id || t.id}`;
    }

    /** True for sub-agent threads spawned by a tool call. */
    get isChildThread() {
        return Boolean(this.props.thread.parent_thread_id);
    }

    get loopsLabel() {
        const n = this.props.thread.loop_count || 0;
        return `${n} loop${n === 1 ? "" : "s"}`;
    }

    /** The ai.session id (a string), shown muted as ``#<id>`` on every node. */
    get sessionIdLabel() {
        return `#${this.props.thread.session_id}`;
    }

    /** True for sessions that ran in the background. Foreground nodes show
        no mode text at all (the flag is rendered only when this is true). */
    get isBackground() {
        return Boolean(this.props.thread.is_background);
    }

    /** Meta line for both root and child threads. The root variant prefixes
        the user name; child threads omit it (always the same as root). The
        per-loop link to the spawning tool call lives in the conversation
        view's user bubbles, not here -- a sidebar row covers the whole
        subagent session, which can have many spawning tool calls. */
    get metaLine() {
        const t = this.props.thread;
        if (this.isChildThread) return this.loopsLabel;
        const userName = t.user_id?.name || "";
        return userName ? `${userName} · ${this.loopsLabel}` : this.loopsLabel;
    }

    /** Most recently started loop on this thread, or null. Picked by
        ``start_time``, with ``id`` as a tiebreaker (also covers the
        transient case where a freshly-inserted loop has not yet received
        a ``start_time``) so a fresh loop always replaces the previous
        one and the label resets. */
    get latestLoop() {
        const loops = this.props.thread.loop_ids;
        if (!loops?.length) return null;
        let latest = null;
        let latestT = -Infinity;
        let latestId = -Infinity;
        for (const l of loops) {
            const t = parseOdooDatetime(l.start_time) ?? -Infinity;
            if (t > latestT || (t === latestT && l.id > latestId)) {
                latestT = t;
                latestId = l.id;
                latest = l;
            }
        }
        return latest;
    }

    /** Combined render data for the elapsed-time label: ``{label, running}``
        or ``null`` if there's nothing to show. Ticks against ``store.now``
        while the latest loop is running, then freezes at ``duration_ms``
        once it ends -- so the row keeps showing how long the last run took.
        ``store.now`` is only read on the running branch, so idle rows don't
        re-render on each tick. The template binds via a single ``t-set``
        so ``latestLoop`` is iterated only once per render. */
    get elapsedDisplay() {
        const loop = this.latestLoop;
        if (!loop) return null;
        if (loop.is_running) {
            const startMs = parseOdooDatetime(loop.start_time);
            if (startMs == null) return null;
            return { label: formatElapsed(this.store.now() - startMs), running: true };
        }
        if (loop.duration_ms != null) {
            return { label: formatElapsed(loop.duration_ms), running: false };
        }
        return null;
    }

    get indents() {
        // Used by t-foreach="indents" to render N indent spacers
        return Array.from({ length: this.props.depth }, (_, i) => i);
    }

    get expanded() {
        return !this.store.isThreadCollapsed(this.props.thread.id);
    }

    toggleExpanded() {
        this.store.setThreadCollapsed(this.props.thread.id, this.expanded);
    }

    onItemClick() {
        this.props.onSelect(this.props.thread.id);
    }
}

// Self-reference for recursive child rendering
ThreadTreeItem.components = { ThreadTreeItem };
