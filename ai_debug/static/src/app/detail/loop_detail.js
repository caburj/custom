/** @odoo-module **/
import { Component } from "@odoo/owl";
import { Notebook } from "@web/core/notebook/notebook";
import { CopyButton } from "@web/core/copy_button/copy_button";
import { useService } from "@web/core/utils/hooks";
import { JsonTree } from "./json_tree";
import { TextPopupDialog } from "./text_popup";
import { formatDuration } from "../format_metrics";
import { extractRagContexts } from "../event_payload";

export class LoopDetail extends Component {
    static template = "ai_debug.LoopDetail";
    static components = { Notebook, CopyButton, JsonTree };
    static props = {
        trace: { type: Object, optional: true },
    };

    setup() {
        try {
            this.dialog = useService("dialog");
        } catch {
            this.dialog = null;
        }
        this.formatDuration = formatDuration;
    }

    openTextPopup(title, content, language) {
        if (!this.dialog) return;
        this.dialog.add(TextPopupDialog, { title, content, language: language || "markdown" });
    }

    get ragContexts() {
        const firstIter = [...this.props.trace.iterations.values()][0];
        if (!firstIter || !firstIter.messages_sent) return null;
        return extractRagContexts(firstIter.messages_sent);
    }

    get instructionsContent() {
        return this.props.trace.instructions || "";
    }

}
