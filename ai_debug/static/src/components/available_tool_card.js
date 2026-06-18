/** @odoo-module **/

import { Component, props, types as t } from "@odoo/owl";
import { FoldableCard } from "@ai_debug/components/foldable_card";
import { TextBlock } from "@ai_debug/components/text_block";
import { JsonViewer } from "@ai_debug/components/json_viewer";

export class AvailableToolCard extends Component {
    static template = "ai_debug.AvailableToolCard";
    static components = { FoldableCard, TextBlock, JsonViewer };
    props = props({
        // Entry produced by the lazy m2m resolver on the iteration's
        // ``available_tool_ids`` field. Shape: {id, state, record}.
        //   - state === "loading": record is null; render a spinner row.
        //   - state === "loaded"  && !record: server returned nothing for
        //                                     this id (tool deleted etc.);
        //                                     render a muted "unavailable"
        //                                     row.
        //   - state === "loaded"  &&  record: render the full foldable card.
        //   - state === "missing": transient; rendered like "loading" --
        //                          the IterationSection ``useEffect`` flips
        //                          it to "loading" on next frame.
        entry: t.object(),
    });

    setup() {
        // Cache the last parse so repeated template reads don't re-parse the
        // same JSON string. Keyed by raw string so a schema edit still re-parses.
        this._schemaCache = { raw: null, value: null };
    }

    /**
     * Parsed ``ai_tool_schema`` JSON, or ``null`` for blank / invalid.
     * Guards for a null record (state "loaded" with missing server row).
     */
    get parsedSchema() {
        const raw = this.props.entry.record?.ai_tool_schema;
        if (!raw || typeof raw !== "string") return null;
        const trimmed = raw.trim();
        if (!trimmed) return null;
        if (this._schemaCache.raw === trimmed) return this._schemaCache.value;
        let value = null;
        try {
            value = JSON.parse(trimmed);
        } catch {
            value = null;
        }
        this._schemaCache = { raw: trimmed, value };
        return value;
    }

}
