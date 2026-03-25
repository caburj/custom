/** @odoo-module **/
import { Component } from "@odoo/owl";
import { Notebook } from "@web/core/notebook/notebook";
import { CopyButton } from "@web/core/copy_button/copy_button";
import { useService } from "@web/core/utils/hooks";
import { JsonTree } from "./json_tree";
import { TextPopupDialog } from "./text_popup";
import { ImagePopupDialog } from "./image_popup";
import { formatTokens, formatDuration } from "../format_metrics";

export class IterationDetail extends Component {
    static template = "ai_debug.IterationDetail";
    static components = { Notebook, CopyButton, JsonTree };
    static props = {
        iteration: { type: Object, optional: true },
    };

    setup() {
        this.formatTokens = formatTokens;
        this.formatDuration = formatDuration;
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

    openImagePopup(title, src) {
        if (!this.dialog) return;
        this.dialog.add(ImagePopupDialog, { title, src });
    }

    get messagesJson() {
        return JSON.stringify(this.props.iteration.messages_sent, null, 2);
    }

    get responseJson() {
        return JSON.stringify(this.props.iteration.raw_response, null, 2);
    }

    get requestJson() {
        return JSON.stringify(this.props.iteration.request_body, null, 2);
    }

    get toolsJson() {
        return JSON.stringify(this.props.iteration.tools, null, 2);
    }

}
