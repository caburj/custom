/** @odoo-module **/

import { Component, proxy, props, types as t } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { CopyButton } from "@web/core/copy_button/copy_button";

export class TextDialog extends Component {
    static template = "ai_debug.TextDialog";
    static components = { Dialog, CopyButton };
    props = props({
        title: t.string(),
        content: t.string(),
        close: t.function(),  // injected by dialog service
    });

    setup() {
        this.state = proxy({ wrap: true });
    }

    toggleWrap() {
        this.state.wrap = !this.state.wrap;
    }
}
