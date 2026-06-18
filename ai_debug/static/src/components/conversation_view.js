/** @odoo-module **/

import { Component, onMounted, onPatched, onWillUnmount, plugin, signal, useEffect, props, types as t } from "@odoo/owl";
import { CopyButton } from "@web/core/copy_button/copy_button";
import { ChatMessage } from "@ai_debug/components/chat_message";
import { LoopDetailStrip } from "@ai_debug/components/loop_detail_strip";
import { htmlToMarkup } from "@ai_debug/components/format";
import { useInfiniteScroll } from "@ai_debug/hooks/use_infinite_scroll";
import { AiDebugStore } from "@ai_debug/store";

const SCROLL_THRESHOLD = 150;
// Brief window to suppress auto-scroll after user-initiated resize (expand/collapse)
const USER_RESIZE_COOLDOWN = 300;

export class ConversationView extends Component {
    static template = "ai_debug.ConversationView";
    static components = { ChatMessage, LoopDetailStrip, CopyButton };
    props = props({
        thread: t.or([t.object(), t.literal(null)]),
        orm: t.object(),
    });

    store = plugin(AiDebugStore);

    setup() {
        this.containerRef = signal(null);
        this.contentRef = signal(null);
        this._scrollPreserve = null;
        this._nearBottom = true;
        this._userResizing = false;
        // Set when _fetchMoreLoops is skipped because a focus-jump is in
        // flight; the effect below retries once isFocusing flips false.
        // Without this, the sentinel's IntersectionObserver fires at most
        // once per visibility transition -- an ignored fire during focus
        // leaves the observer stuck, so loop #1 (or whatever is still
        // unloaded) would never fetch until the user scrolled the sentinel
        // out and back in.
        this._pendingFetchMore = false;

        this.sentinelRef = signal(null);
        useInfiniteScroll({
            scrollRef: this.containerRef,
            sentinelRef: this.sentinelRef,
            onIntersect: () => this._fetchMoreLoops(),
        });

        useEffect(() => {
            if (!this.store.isFocusing() && this._pendingFetchMore) {
                this._pendingFetchMore = false;
                this._fetchMoreLoops();
            }
        });

        // Trigger the initial fetch on thread change. We can't rely on the
        // sentinel observer alone: ``onMounted`` scrolls to bottom, pushing
        // the top sentinel out of view, so its initial intersection check
        // doesn't fire. Worse, when the user switches between threads the
        // conversation view is reused (not remounted), the sentinel DOM
        // element persists, and ``useInfiniteScroll``'s reconcile is a
        // no-op -- so the observer never re-fires. With ``fetchThreads``
        // pre-populating loop stubs, that left the view rendering "No
        // message" for every loop until the user manually scrolled up.
        useEffect(() => {
            const thread = this.props.thread;
            if (thread && !this.store.hasInitialFetch(thread.id)) {
                this._fetchMoreLoops();
            }
        });

        onMounted(() => {
            this._scrollToBottom();
            const contentEl = this.contentRef();
            if (contentEl) {
                this._observer = new ResizeObserver(() => {
                    if (this._nearBottom && !this._userResizing) {
                        this._scrollToBottom();
                    }
                });
                this._observer.observe(contentEl);
            }
            this.containerRef()?.addEventListener("scroll", this._onScroll);
            this.containerRef()?.addEventListener("user-toggle", this._onUserToggle);
        });

        onPatched(() => {
            if (!this._scrollPreserve) return;
            const container = this.containerRef();
            if (!container) return;
            const thread = this.props.thread;
            const store = this.store;
            // Discard if thread changed while loading.
            if (!thread || thread.id !== this._scrollPreserve.threadId) {
                this._scrollPreserve = null;
                return;
            }
            if (store.isLoading(thread.id)) {
                // Refresh prevScrollHeight so the delta reflects the layout
                // the user is actually seeing (spinner included). Without
                // this, the spinner's height contributes to the delta and
                // the content appears pulled up by that amount when the
                // spinner is removed on restore.
                this._scrollPreserve.prevScrollHeight = container.scrollHeight;
                return;
            }
            const delta = container.scrollHeight - this._scrollPreserve.prevScrollHeight;
            if (delta > 0) {
                container.scrollTop += delta;
            }
            this._scrollPreserve = null;
        });

        onWillUnmount(() => {
            this._observer?.disconnect();
            this.containerRef()?.removeEventListener("scroll", this._onScroll);
            this.containerRef()?.removeEventListener("user-toggle", this._onUserToggle);
        });
    }

    async _fetchMoreLoops() {
        const thread = this.props.thread;
        const store = this.store;
        const orm = this.props.orm;
        if (!thread || store.isLoading(thread.id) || store.isFullyLoaded(thread.id)) {
            return;
        }
        // Suppress while a focus-jump is in flight: a smooth-scroll that
        // crosses the sentinel would otherwise fetch older loops and
        // shift the target's Y before the scroll lands. Mark pending so
        // the useEffect on store.isFocusing re-runs this once focus ends;
        // otherwise an ignored sentinel fire during focus leaves the
        // observer stuck in "last seen visible" state and the next page
        // never loads.
        if (store.isFocusing()) {
            this._pendingFetchMore = true;
            return;
        }

        const container = this.containerRef();
        if (container) {
            this._scrollPreserve = {
                prevScrollHeight: container.scrollHeight,
                threadId: thread.id,
            };
        }

        // Gate on the store's initial-fetch flag, not on loop_ids.length:
        // ``fetchThreads`` pre-populates partial loop stubs for subagent
        // threads (so the parent's tool-call cards can render badges
        // immediately), which would make this think the thread is already
        // loaded and switch to scroll-up mode. The scroll-up "before
        // oldest stub" query then finds nothing, marks the thread fully
        // loaded, and the bodies/iterations never arrive.
        if (!store.hasInitialFetch(thread.id)) {
            await store.fetchLoops(orm, thread.id, { last: 10 });
        } else {
            const loadedLoops = thread.loop_ids;
            if (loadedLoops.length) {
                await store.fetchLoops(orm, thread.id, { before: loadedLoops[0].id, limit: 10 });
            }
        }
    }

    _onUserToggle = () => {
        this._userResizing = true;
        clearTimeout(this._userResizeTimer);
        this._userResizeTimer = setTimeout(() => {
            this._userResizing = false;
        }, USER_RESIZE_COOLDOWN);
    };

    _onScroll = () => {
        const el = this.containerRef();
        if (!el) return;
        this._nearBottom =
            el.scrollHeight - el.scrollTop - el.clientHeight < SCROLL_THRESHOLD;
    };

    toMarkup(html) {
        return htmlToMarkup(html);
    }

    /** Click handler for a child-thread loop's "← from <tool>" back-link.
        The parent thread is read off the current thread record (it's the
        same for every loop in a given child thread); the focus jump
        delegates to the store, which fetches loops on the parent thread
        if pagination hasn't reached the target yet. */
    onJumpToParentCall(loop) {
        const parentCall = loop.parent_tool_call_id;
        const parentThreadId = this.props.thread.parent_thread_id?.id;
        if (!parentCall?.id || !parentThreadId) return;
        this.store.focusToolCall(this.props.orm, parentThreadId, parentCall.id);
    }

    _scrollToBottom() {
        const el = this.containerRef();
        if (!el) return;
        el.scrollTop = el.scrollHeight;
        this._nearBottom = true;
    }
}
