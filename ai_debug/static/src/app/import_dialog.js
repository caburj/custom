/** @odoo-module **/
import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class ImportPreviewDialog extends Component {
    static template = "ai_debug.ImportPreviewDialog";
    static components = { Dialog };
    static props = {
        traceCount: Number,
        duplicateCount: Number,
        onConfirm: Function,
        close: Function,        // Injected by dialog service
        errorMessage: { type: String, optional: true },
    };
}
