/** @odoo-module **/

import { whenReady } from "@odoo/owl";
import { mountComponent } from "@web/env";
import { services } from "@web/core/services";
import { AiDebugApp } from "@ai_debug/app";
import { AiDebugStore } from "@ai_debug/store";

// Register the store alongside the framework service-plugins so the root
// AiDebugApp's class field ``store = plugin(AiDebugStore)`` resolves at
// construction time. providePlugins() runs in setup(), which is too late
// for class fields on the root component.
//
// NB: register into the shared ``services`` Resource rather than passing
// ``{ plugins: [AiDebugStore] }`` to mountComponent -- that would override
// the App's default ``plugins: services`` set and drop every framework
// service-plugin (most visibly LocalizationPlugin, leaving translations
// unloaded so the first translated template text throws and the page goes
// blank).
services.add(AiDebugStore);

whenReady(() => mountComponent(AiDebugApp, document.body));
