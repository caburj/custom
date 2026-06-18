/** @odoo-module **/

import { Component, plugin, props, signal, types as t } from "@odoo/owl";
import { useInfiniteScroll } from "@ai_debug/hooks/use_infinite_scroll";
import { ThreadTreeItem } from "@ai_debug/components/thread_tree_item";
import { ImportButton } from "@ai_debug/components/import_export_bar";
import { AiDebugStore } from "@ai_debug/store";

export class ThreadSidebar extends Component {
    static template = "ai_debug.ThreadSidebar";
    static components = { ThreadTreeItem, ImportButton };
    props = props({
        selectedThreadId: t.or([t.number(), t.literal(null)]),
        onSelectThread: t.function(),
        onToggle: t.function().optional(),
        orm: t.object(),
    });

    store = plugin(AiDebugStore);

    setup() {
        this.listRef = signal(null);
        this.sentinelRef = signal(null);
        useInfiniteScroll({
            scrollRef: this.listRef,
            sentinelRef: this.sentinelRef,
            onIntersect: () => this._fetchOlderThreads(),
            alwaysReconnect: true,
        });
    }

    async _fetchOlderThreads() {
        const { orm } = this.props;
        const store = this.store;
        if (store.threadListLoading || store.threadListFullyLoaded) return;
        await store.fetchThreads(orm, { limit: 20 });
    }

    get rootThreads() {
        return this.store.rootThreads();
    }

    /** True iff at least one thread in the forest has children — the
        "toggle all" header button only makes sense when something is
        actually foldable. */
    get hasExpandableThreads() {
        const walk = (t) => {
            if ((t.child_thread_ids?.length || 0) > 0) return true;
            return (t.child_thread_ids || []).some(walk);
        };
        return this.rootThreads.some(walk);
    }

    /** True iff every foldable thread in the forest is currently expanded. */
    get allExpanded() {
        const store = this.store;
        const walk = (t) => {
            if ((t.child_thread_ids?.length || 0) === 0) return true;
            if (store.isThreadCollapsed(t.id)) return false;
            return t.child_thread_ids.every(walk);
        };
        return this.rootThreads.every(walk);
    }

    onToggleAll() {
        const store = this.store;
        if (this.allExpanded) {
            store.collapseAllThreads(this.rootThreads);
        } else {
            store.expandAllThreads();
        }
    }
}
