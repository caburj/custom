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
