/** @odoo-module **/

import { Component, props, types as t } from "@odoo/owl";

export class ErrorBanner extends Component {
    static template = "ai_debug.ErrorBanner";

    props = props({ message: t.string() });
}
