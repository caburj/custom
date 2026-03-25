/** @odoo-module **/
import { Component } from "@odoo/owl";
import { Notebook } from "@web/core/notebook/notebook";
import { CopyButton } from "@web/core/copy_button/copy_button";
import { useService } from "@web/core/utils/hooks";
import { JsonTree } from "./json_tree";
import { TextPopupDialog } from "./text_popup";
import { formatTokens, formatDuration } from "../format_metrics";

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
        this.formatTokens = formatTokens;
        this.formatDuration = formatDuration;
    }

    openTextPopup(title, content, language) {
        if (!this.dialog) return;
        this.dialog.add(TextPopupDialog, { title, content, language: language || "markdown" });
    }

    /**
     * Extract text from a provider-formatted message.
     * OpenAI: {content: [{type: 'input_text', text: '...'}, ...]}
     * Google: {parts: [{text: '...'}, ...]}
     * Legacy: {content: '...'}
     */
    _getMessageText(msg) {
        if (typeof msg.content === "string") return msg.content;
        if (Array.isArray(msg.content)) {
            return msg.content
                .filter(p => typeof p.text === "string")
                .map(p => p.text)
                .join("\n");
        }
        if (Array.isArray(msg.parts)) {
            return msg.parts
                .filter(p => typeof p.text === "string")
                .map(p => p.text)
                .join("\n");
        }
        return "";
    }

    get ragContextMessages() {
        const firstIter = [...this.props.trace.iterations.values()][0];
        if (!firstIter || !firstIter.messages_sent) return null;
        const instructions = this.props.trace.instructions;
        return firstIter.messages_sent
            .filter(m => m.role === "system" && this._getMessageText(m) !== instructions)
            .map(m => ({ ...m, _text: this._getMessageText(m) }));
    }

    get instructionsContent() {
        return this.props.trace.instructions || "";
    }

    get iterationRows() {
        return [...this.props.trace.iterations.values()].map((iter, i) => ({
            index: iter.iteration_index ?? i + 1,
            duration_ms: iter.duration_ms || 0,
            tokens: iter.tokens || { input: 0, output: 0, cache_read: 0, reasoning: 0, total: 0 },
        }));
    }

    get traceTotals() {
        let total_input = 0, total_output = 0, total_cached = 0,
            total_reasoning = 0, total_duration_ms = 0;
        for (const iter of this.props.trace.iterations.values()) {
            const t = iter.tokens;
            if (t) {
                total_input += t.input || 0;
                total_output += t.output || 0;
                total_cached += t.cache_read || 0;
                total_reasoning += t.reasoning || 0;
            }
            total_duration_ms += iter.duration_ms || 0;
        }
        return { total_input, total_output, total_cached, total_reasoning, total_duration_ms };
    }

}
