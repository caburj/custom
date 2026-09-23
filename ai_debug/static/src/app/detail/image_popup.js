/** @odoo-module **/
import { Component, t, useProps } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class ImagePopupDialog extends Component {
    static template = "ai_debug.ImagePopupDialog";
    static components = { Dialog };
    props = useProps({
        title: t.string(),
        src: t.string(),
        close: t.function(),
    });
}
