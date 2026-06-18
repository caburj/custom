/** @odoo-module **/

import { onMounted, onPatched, onWillUnmount, signal } from "@odoo/owl";

/**
 * OWL hook that tracks whether an element overflows its visible box on
 * the horizontal axis. Re-measures on mount, on every patch (so content
 * changes register even when the box keeps the same outer size), and
 * whenever the element is resized (via ResizeObserver).
 *
 * @param {import("@odoo/owl").Signal<HTMLElement|null>} ref - signal holding the element
 * @returns {import("@odoo/owl").Signal<boolean>} true when content overflows horizontally
 */
export function useOverflowDetection(ref) {
    const overflow = signal(false);
    let observer = null;
    let observedEl = null;

    const measure = () => {
        const el = ref();
        if (!el) {
            if (overflow()) overflow.set(false);
            return;
        }
        const o = el.scrollWidth > el.clientWidth;
        if (o !== overflow()) overflow.set(o);
    };

    const ensureObserver = () => {
        const el = ref();
        if (el === observedEl) return;
        if (observer) { observer.disconnect(); observer = null; }
        observedEl = el;
        if (el) {
            observer = new ResizeObserver(measure);
            observer.observe(el);
        }
    };

    onMounted(() => { ensureObserver(); measure(); });
    onPatched(() => { ensureObserver(); measure(); });
    onWillUnmount(() => observer?.disconnect());

    return overflow;
}
