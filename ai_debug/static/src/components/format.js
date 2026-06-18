/** @odoo-module **/

import { markup } from "@odoo/owl";

/**
 * Wrap an HTML string as trusted OWL markup for use with t-out.
 */
export function htmlToMarkup(html) {
    if (!html) return "";
    return markup(html);
}

export function formatDuration(ms) {
    if (ms == null) return "\u2014";
    if (ms < 1000) return `${ms}ms`;
    const s = ms / 1000;
    if (s < 60) return `${s.toFixed(1)}s`;
    const m = Math.floor(s / 60);
    const rem = Math.round(s % 60);
    return `${m}m ${rem}s`;
}

export function formatTokens(n) {
    if (n == null || n === 0) return "0";
    if (n < 1000) return String(n);
    if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
    return `${(n / 1_000_000).toFixed(1)}M`;
}
