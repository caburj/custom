/** @odoo-module **/

/**
 * Format a token count with smart abbreviation.
 * < 1000: exact number (e.g. "450")
 * >= 1000: one decimal "k" (e.g. "3.4k")
 * >= 1000000: one decimal "M" (e.g. "1.2M")
 * Falsy/0 returns "0".
 */
export function formatTokens(n) {
    if (!n) return "0";
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
    return String(n);
}

/**
 * Format a duration in milliseconds with adaptive units.
 * null/undefined: "\u2013" (en dash)
 * < 1000ms: "850ms"
 * < 60000ms: "1.2s"
 * >= 60000ms: "2m 14s"
 */
export function formatDuration(ms) {
    if (!ms && ms !== 0) return "\u2013";
    if (ms < 1000) return `${Math.round(ms)}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    const mins = Math.floor(ms / 60000);
    const secs = Math.round((ms % 60000) / 1000);
    return `${mins}m ${secs}s`;
}

/** @param {number} count */
export function formatCount(count) {
    return count.toLocaleString();
}

/** @param {number} credits */
export function formatCredits(credits) {
    if (credits !== 0 && Math.abs(credits) < 0.0005) {
        return credits.toExponential(2);
    }
    return credits.toLocaleString(undefined, { maximumFractionDigits: 3 });
}

/**
 * Aggregate captured iterations across the selected trace and its descendants.
 * @param {{ iterations: Map<string, {
 *     tokens: { input: number, output: number, cache_read: number, total: number } | null,
 *     cost: number | null,
 * }> }[]} traces
 */
export function getTraceTotals(traces) {
    const totals = {
        total_input: 0,
        total_output: 0,
        total_cached: 0,
        total_tokens: 0,
        total_cost: 0,
        iteration_count: 0,
        usage_count: 0,
        cost_count: 0,
        has_token_metrics: false,
    };
    for (const trace of traces) {
        totals.iteration_count += trace.iterations.size;
        for (const iteration of trace.iterations.values()) {
            if (iteration.tokens) {
                totals.usage_count++;
                totals.total_input += iteration.tokens.input;
                totals.total_output += iteration.tokens.output;
                totals.total_cached += iteration.tokens.cache_read;
                totals.total_tokens += iteration.tokens.total;
            }
            if (iteration.cost != null) {
                totals.cost_count++;
                totals.total_cost += iteration.cost;
            }
        }
    }
    totals.has_token_metrics = totals.usage_count > 0;
    return totals;
}
