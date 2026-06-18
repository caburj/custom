/** @odoo-module **/

import { Component, props, types as t } from "@odoo/owl";
import { CopyButton } from "@web/core/copy_button/copy_button";
import { htmlToMarkup } from "@ai_debug/components/format";

export class ChatMessage extends Component {
    static template = "ai_debug.ChatMessage";
    static components = { CopyButton };
    props = props({
        role: t.string(),
        content: t.string().optional(),
        isTyping: t.boolean().optional(),
        userName: t.string().optional(),
        agentName: t.string().optional(),
        modelName: t.string().optional(),
        iconClass: t.string().optional(),
        slots: t.object().optional(),
    });

    get label() {
        if (this.props.role === "user") {
            return this.props.userName || "User";
        }
        return this.props.agentName || "Agent";
    }

    get icon() {
        if (this.props.iconClass) {
            return this.props.iconClass;
        }
        return this.props.role === "user" ? "fa-user" : "fa-android";
    }

    get showTyping() {
        return this.props.isTyping && !this.props.content;
    }

    get contentMarkup() {
        return htmlToMarkup(this.props.content);
    }
}
