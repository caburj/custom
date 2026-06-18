/** @odoo-module **/

/**
 * Concatenate per-iteration deltas up to and including `iteration` to
 * reconstruct the full `messages` list that was sent to the LLM at the
 * moment `iteration` ran.
 *
 * Invariant: `iteration.loop_id.iteration_ids` is ordered by `sequence`
 * ascending (enforced by the store's model descriptor — see store.js).
 *
 * @param {Object} iteration  an ai.debug.iteration record (Proxy or plain object)
 * @returns {Array} concatenated deltas; empty array if the loop is unavailable.
 */
export function reconstructMessagesSent(iteration) {
    const siblings = iteration?.loop_id?.iteration_ids;
    if (!siblings || !siblings.length) {
        return [];
    }
    const result = [];
    for (const sib of siblings) {
        if (sib.sequence > iteration.sequence) {
            break;
        }
        if (sib.messages_delta) {
            result.push(...sib.messages_delta);
        }
    }
    return result;
}
