/** @odoo-module **/
import { _t } from "@web/core/l10n/translation";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";

function openAiDebugger() {
    return {
        type: "item",
        description: _t("Open AI Debugger"),
        href: "/ai-debug",
        callback: () => {
            browser.open("/ai-debug", "_blank");
        },
        sequence: 700,
        section: "tools",
    };
}

registry.category("debug").category("default").add("openAiDebugger", openAiDebugger);
