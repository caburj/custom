/** @odoo-module **/

import { Component, signal, props, types as t } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { CopyButton } from "@web/core/copy_button/copy_button";
import { TextDialog } from "@ai_debug/components/text_dialog";
import { useOverflowDetection } from "@ai_debug/hooks/use_overflow_detection";

/**
 * Single-line bordered text box. Newlines collapse to spaces; content
 * wider than the box is clipped with an ellipsis. When clipped, the box
 * becomes clickable and opens the full text in a ``TextDialog``. A copy
 * button is shown on hover.
 *
 * Renders nothing when ``text`` is falsy.
 */
export class TextBlock extends Component {
    static template = "ai_debug.TextBlock";
    static components = { CopyButton };
    props = props({
        text: t.or([t.string(), t.literal(null)]).optional(),
        dialogTitle: t.string(),
    });

    setup() {
        this.dialog = useService("dialog");
        this.preRef = signal(null);
        this.overflow = useOverflowDetection(this.preRef);
    }

    onClick() {
        if (!this.overflow()) return;
        this.dialog.add(TextDialog, {
            title: this.props.dialogTitle,
            content: this.props.text,
        });
    }
}
