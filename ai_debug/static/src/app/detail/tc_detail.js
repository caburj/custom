/** @odoo-module **/
import { Component } from "@odoo/owl";
import { Notebook } from "@web/core/notebook/notebook";
import { CopyButton } from "@web/core/copy_button/copy_button";
import { useService } from "@web/core/utils/hooks";
import { JsonTree } from "./json_tree";
import { TextPopupDialog } from "./text_popup";

export class ToolCallDetail extends Component {
    static template = "ai_debug.ToolCallDetail";
    static components = { Notebook, CopyButton, JsonTree };
    static props = {
        toolCall: Object,
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

    get argsJson() {
        return JSON.stringify(this.props.toolCall.args, null, 2);
    }

    get resultString() {
        const result = this.props.toolCall.result;
        if (result !== null && typeof result === "object") {
            return JSON.stringify(result, null, 2);
        }
        return String(result);
    }

    get resultIsObject() {
        const result = this.props.toolCall.result;
        return result !== null && typeof result === "object";
    }

    get resultIsLong() {
        return !this.resultIsObject && this.resultString.length > 300;
    }

}
