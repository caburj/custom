/** @odoo-module **/
import { mountComponent } from "@web/env";
import { AiDebugApp } from "./app";
import { whenReady } from "@odoo/owl";

whenReady(async () => {
    await mountComponent(AiDebugApp, document.body, { name: "AI Debug" });
});
