/** @odoo-module **/

import { signal } from "@odoo/owl";
import { KeepLast } from "@web/core/utils/concurrency";

/**
 * Wrap *method* so re-entries are ignored while one call is still pending.
 * Acts like a per-component mutex: the second click during an in-flight
 * call silently drops (returns undefined).
 *
 * Copied from @point_of_sale/app/hooks/hooks (the POS hooks aren't safe
 * to import from an unrelated module — it would pull in the whole POS
 * bundle and couple ai_debug to point_of_sale).
 */
export function useAsyncLockedMethod(method) {
    let called = false;
    return async (...args) => {
        if (called) return;
        try {
            called = true;
            return await method(...args);
        } finally {
            called = false;
        }
    };
}

/**
 * Wrap an async function and expose its call status reactively via signals,
 * so a component can disable a button / swap in a spinner without hand-rolled
 * try/finally bookkeeping every time.
 *
 * Usage:
 *   this.doFetch = useTrackedAsync((orm, id) => orm.call(...));
 *   // this.doFetch.status() is "idle" | "loading" | "success" | "error"
 *   // this.doFetch.call(orm, 5) fires the async
 *   // this.doFetch.result() holds the return value or the thrown error
 *
 * Concurrency:
 *   - default:       reentrant calls while loading are dropped
 *                    (useAsyncLockedMethod semantics).
 *   - keepLast=true: newest call supersedes older, older result discarded
 *                    (KeepLast semantics).
 *
 * @param {(...args: any[]) => Promise<any>} asyncFn
 * @param {{ keepLast?: boolean }} [options]
 */
export function useTrackedAsync(asyncFn, options = {}) {
    const status   = signal("idle");
    const result   = signal(null);
    const lastArgs = signal(null);
    const { keepLast = false } = options;

    const baseMethod = async (...args) => {
        status.set("loading");
        result.set(null);
        lastArgs.set(args);
        try {
            const r = await asyncFn(...args);
            status.set("success");
            result.set(r);
        } catch (error) {
            status.set("error");
            result.set(error);
        }
    };

    let call;
    if (keepLast) {
        const keepLastInstance = new KeepLast();
        call = (...args) => keepLastInstance.add(baseMethod(...args));
    } else {
        call = useAsyncLockedMethod(baseMethod);
    }

    return { status, result, lastArgs, call };
}
