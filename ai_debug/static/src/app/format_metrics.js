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
