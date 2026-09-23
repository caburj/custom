/** @odoo-module **/
import { Component, t, useProps } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class ImportPreviewDialog extends Component {
    static template = "ai_debug.ImportPreviewDialog";
    static components = { Dialog };
    props = useProps({
        traceCount: t.number(),
        duplicateCount: t.number(),
        onConfirm: t.function(),
        close: t.function(),        // Injected by dialog service
        errorMessage: t.string().optional(),
    });
}
