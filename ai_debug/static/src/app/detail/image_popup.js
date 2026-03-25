/** @odoo-module **/
import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class ImagePopupDialog extends Component {
    static template = "ai_debug.ImagePopupDialog";
    static components = { Dialog };
    static props = {
        title: String,
        src: String,
        close: Function,
    };
}
