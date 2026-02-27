/** @odoo-module **/
import { Component, onMounted, useRef, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { CopyButton } from "@web/core/copy_button/copy_button";

export class TextPopupDialog extends Component {
    static template = "ai_debug.TextPopupDialog";
    static components = { Dialog, CopyButton };
    static props = {
        title: String,
        content: String,
        language: { type: String, optional: true },
        close: Function,  // Injected by dialog service
    };

    setup() {
        this.codeRef = useRef("codeEl");
        this.state = useState({ wrap: true });
        onMounted(() => {
            const el = this.codeRef.el;
            if (!el) return;
            el.textContent = this.props.content;
            // Apply Prism highlighting if available
            const lang = this.props.language || "json";
            if (window.Prism && Prism.languages[lang]) {
                try {
                    Prism.highlightElement(el);
                } catch {
                    // Fallback: textContent already set above
                }
            }
        });
    }

    toggleWrap() {
        this.state.wrap = !this.state.wrap;
    }
}
