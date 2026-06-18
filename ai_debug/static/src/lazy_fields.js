/** @odoo-module **/

/**
 * Per-model, per-field configuration for lazy m2m resolution.
 *
 * When a Record proxy reads an m2m field listed here, instead of resolving
 * each id to a full Record synchronously, we return an array of typed
 * entries (``{id, state, record}``) and schedule a batched ``search_read``
 * on the related model. Subsequent reads see the loaded records in the
 * bucket and return ``state: "loaded"``.
 *
 * ``fields`` is the list passed to ``search_read`` on the related model.
 * ``llm_name`` is a non-stored computed field on ``ir.actions.server``
 * declared by the ``ai_debug`` module; keeps the LLM-facing tool name
 * computation on the server where ``make_tool_name`` already lives.
 *
 * Lives in its own module to avoid a store <-> record import cycle: store
 * imports symbols from record, and record imports this config.
 */
export const LAZY_FIELDS = {
    "ai.debug.iteration": {
        available_tool_ids: {
            relation: "ir.actions.server",
            fields: ["display_name", "llm_name", "ai_tool_description", "ai_tool_schema"],
        },
    },
};
