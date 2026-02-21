/** @odoo-module **/
import { Component } from "@odoo/owl";
import { Notebook } from "@web/core/notebook/notebook";
import { CopyButton } from "@web/core/copy_button/copy_button";
import { useService } from "@web/core/utils/hooks";
import { JsonTree } from "./json_tree";
import { TextPopupDialog } from "./text_popup";

export class LoopDetail extends Component {
    static template = "ai_debug.LoopDetail";
    static components = { Notebook, CopyButton, JsonTree };
    static props = {
        trace: Object,
    };

    setup() {
        try {
            this.dialog = useService("dialog");
        } catch {
            this.dialog = null;
        }
    }

    openTextPopup(title, content, language) {
        if (!this.dialog) return;
        this.dialog.add(TextPopupDialog, { title, content, language: language || "markdown" });
    }

    get ragContextMessages() {
        const firstIter = [...this.props.trace.iterations.values()][0];
        if (!firstIter || !firstIter.messages_sent) return null;
        return firstIter.messages_sent.filter(
            m => m.role === "system" && m.content !== this.props.trace.instructions
        );
    }

    get instructionsContent() {
        return this.props.trace.instructions || "";
    }

    get toolsJson() {
        return JSON.stringify(this.props.trace.tools, null, 2);
    }
}
