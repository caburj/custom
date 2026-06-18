/** @odoo-module **/

import { onMounted, onPatched, onWillUnmount } from "@odoo/owl";

/**
 * OWL hook that manages an IntersectionObserver on a sentinel element
 * inside a scrollable container. When the sentinel becomes visible,
 * `onIntersect` is called (typically to fetch the next page).
 *
 * @param {Object} params
 * @param {import("@odoo/owl").Signal<HTMLElement|null>} params.scrollRef
 *     Signal holding the scrollable container element (used as IntersectionObserver root)
 * @param {import("@odoo/owl").Signal<HTMLElement|null>} params.sentinelRef
 *     Signal holding the sentinel element
 * @param {() => void} params.onIntersect - called when the sentinel is visible
 * @param {boolean} [params.alwaysReconnect=false] - when true, the observer is
 *     disconnected and re-created on every patch. Use this when new items are
 *     appended *above* the sentinel (keeping it in view), so a fresh observer
 *     re-fires its initial intersection check. When false (default), reconnect
 *     only happens when the sentinel DOM element changes (e.g. after a t-if flip).
 */
export function useInfiniteScroll({ scrollRef, sentinelRef, onIntersect, alwaysReconnect = false }) {
    let observer = null;
    let observedEl = null;

    function reconcile() {
        const el = sentinelRef();
        if (!alwaysReconnect && el === observedEl) return;
        observer?.disconnect();
        observedEl = null;
        if (el) {
            observer = new IntersectionObserver(
                (entries) => { if (entries[0]?.isIntersecting) onIntersect(); },
                { root: scrollRef(), threshold: 0 },
            );
            observer.observe(el);
            observedEl = el;
        }
    }

    onMounted(reconcile);
    onPatched(reconcile);
    onWillUnmount(() => observer?.disconnect());
}
