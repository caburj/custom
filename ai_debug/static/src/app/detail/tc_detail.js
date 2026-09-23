/** @odoo-module **/
import { Component, t, useProps } from "@odoo/owl";
import { Notebook } from "@web/core/notebook/notebook";
import { CopyButton } from "@web/core/copy_button/copy_button";
import { useService } from "@web/core/utils/hooks";
import { JsonTree } from "./json_tree";
import { TextPopupDialog } from "./text_popup";
import { ImagePopupDialog } from "./image_popup";
import { formatDuration } from "../format_metrics";

function parseJsonContentData(part) {
    const data = part?.type === "text" ? part.content?.data : undefined;
    if (typeof data !== "string") {
        return part;
    }
    try {
        const parsed = JSON.parse(data);
        if (parsed === null || typeof parsed !== "object") {
            return part;
        }
        return { ...part, content: { ...part.content, data: parsed } };
    } catch {
        return part;
    }
}

export class ToolCallDetail extends Component {
    static template = "ai_debug.ToolCallDetail";
    static components = { Notebook, CopyButton, JsonTree };
    props = useProps({
        toolCall: t.object().optional(),
    });

    setup() {
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

    get fullToolCallJson() {
        const tc = this.props.toolCall;
        return JSON.stringify({
            tool_name: tc.tool_name,
            tool_status: tc.tool_status,
            summary: tc.summary,
            args: tc.args,
            result: tc.result,
            duration_ms: tc.duration_ms,
        }, null, 2);
    }

    get argsJson() {
        return JSON.stringify(this.props.toolCall.args, null, 2);
    }

    get resultString() {
        const result = this.renderedResult;
        if (result !== null && typeof result === "object") {
            return JSON.stringify(result, null, 2);
        }
        return String(result);
    }

    get renderedResult() {
        const result = this.props.toolCall.result;
        return Array.isArray(result) ? result.map(parseJsonContentData) : result;
    }

    get resultIsObject() {
        const result = this.renderedResult;
        return result !== null && typeof result === "object";
    }

    get resultIsLong() {
        return !this.resultIsObject && this.resultString.length > 300;
    }

    get hasConfirmation() {
        return !!this.props.toolCall.triggered_confirmation;
    }

}
