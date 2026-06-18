/** @odoo-module **/

import { Component, plugin, props } from "@odoo/owl";
import { AiDebugStore } from "@ai_debug/store";

/**
 * Top-of-page banner shown whenever ``store.isImported`` is true. Makes
 * the imported-vs-live distinction obvious and offers a one-click
 * "Return to live" action that reloads the page (drops imported state,
 * re-runs the live boot path).
 */
export class ImportedBanner extends Component {
    static template = "ai_debug.ImportedBanner";
    props = props({});

    store = plugin(AiDebugStore);

    get meta() {
        return this.store.importMeta() || {};
    }

    onReturnToLive() {
        window.location.reload();
    }
}
