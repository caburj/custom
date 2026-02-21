/** @odoo-module **/
import { Component } from "@odoo/owl";
import { Notebook } from "@web/core/notebook/notebook";
import { CopyButton } from "@web/core/copy_button/copy_button";
import { useService } from "@web/core/utils/hooks";
import { JsonTree } from "./json_tree";
import { TextPopupDialog } from "./text_popup";
import { StateDiff } from "./state_diff";

export class IterationDetail extends Component {
    static template = "ai_debug.IterationDetail";
    static components = { Notebook, CopyButton, JsonTree, StateDiff };
    static props = {
        iteration: Object,
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

    get messagesJson() {
        return JSON.stringify(this.props.iteration.messages_sent, null, 2);
    }

    get responseJson() {
        return JSON.stringify(this.props.iteration.raw_response, null, 2);
    }

    // State diff comes from tool calls in this iteration, NOT from the iteration payload itself.
    // Collect state_before from the first tool call and state_after from the last tool call.
    get stateBefore() {
        const toolCalls = [...this.props.iteration.toolCalls.values()];
        if (toolCalls.length === 0) return null;
        return toolCalls[0].state_before;
    }

    get stateAfter() {
        const toolCalls = [...this.props.iteration.toolCalls.values()];
        if (toolCalls.length === 0) return null;
        return toolCalls[toolCalls.length - 1].state_after;
    }
}
