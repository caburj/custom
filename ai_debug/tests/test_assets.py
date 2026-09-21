from odoo.modules.module import get_manifest
from odoo.tests import HttpCase, TransactionCase, tagged


BUS_ASSETS = {
    "bus/static/src/bus_parameters_plugin.js",
    "bus/static/src/multi_tab_fallback_plugin.js",
    "bus/static/src/multi_tab_shared_worker_plugin.js",
    "bus/static/src/multi_tab_plugin.js",
    "bus/static/src/services/worker_plugin.js",
    "bus/static/src/services/bus_plugin.js",
}


@tagged("post_install", "-at_install")
class TestAiDebugAssets(TransactionCase):
    def _asset_paths(self, bundle):
        return [
            asset[0].removeprefix("/")
            for asset in self.env["ir.asset"]._get_asset_paths(bundle, {})
        ]

    def test_standalone_bundle_runtime_boundary(self):
        paths = self._asset_paths("ai_debug.assets")
        runtime_paths = [path for path in paths if path.endswith((".js", ".xml"))]
        bus_paths = {
            path
            for path in runtime_paths
            if path.startswith("bus/static/src/")
        }

        self.assertEqual(bus_paths, BUS_ASSETS)
        self.assertIn("web/static/src/env.js", paths)
        self.assertIn("web/static/src/core/main_components_container.js", paths)
        self.assertIn("web/static/src/core/dialog/dialog_plugin.js", paths)
        self.assertIn("web/static/src/core/overlay/overlay_container.js", paths)
        self.assertFalse(any(path.startswith("mail/") for path in runtime_paths))
        self.assertFalse(any(path.startswith(("ai/", "ai_agentic/")) for path in runtime_paths))
        self.assertFalse(
            any(path.startswith("web/static/src/webclient/") for path in runtime_paths)
        )
        self.assertNotIn("web/static/src/public/public_root_instance.js", paths)
        self.assertNotIn("bus/static/src/workers/bus_worker_script.js", paths)
        self.assertNotIn("ai_debug/static/src/debug_menu_button.js", paths)

    def test_debug_menu_stays_in_webclient_bundle(self):
        paths = self._asset_paths("web.assets_backend")

        self.assertIn("ai_debug/static/src/debug_menu_button.js", paths)

    def test_light_and_dark_bundle_order(self):
        light_paths = self._asset_paths("ai_debug.assets")
        dark_paths = self._asset_paths("ai_debug.assets_dark")
        app_styles = "ai_debug/static/src/app/app.scss"
        app_dark_styles = "ai_debug/static/src/app/app.dark.scss"
        core_dark_styles = "web/static/src/core/datetime/datetime_picker.dark.scss"
        dark_directives = get_manifest("ai_debug")["assets"]["ai_debug.assets_dark"]

        self.assertIn(app_styles, light_paths)
        self.assertNotIn(app_dark_styles, light_paths)
        self.assertNotIn(core_dark_styles, light_paths)
        self.assertIn(core_dark_styles, dark_paths)
        self.assertLess(dark_paths.index(app_styles), dark_paths.index(app_dark_styles))
        self.assertEqual(
            dark_directives[:2],
            [("include", "ai_debug.assets"), ("include", "web.dark_mode_variables")],
        )


@tagged("post_install", "-at_install")
class TestAiDebugRuntime(HttpCase):
    def test_runtime_services_exclude_mail_chat_hub(self):
        self.browser_js(
            url_path="/ai-debug?debug=assets",
            ready="Boolean(document.querySelector('.ai-debug-app') && odoo.__WOWL_DEBUG__?.root)",
            login="admin",
            code="""
                const { registry } = odoo.loader.modules.get("@web/core/registry");
                const root = odoo.__WOWL_DEBUG__.root;
                const services = root.env.services;
                const mainComponents = registry.category("main_components");
                const failures = [];
                for (const service of ["bus_service", "dialog", "overlay"]) {
                    if (!(service in services)) {
                        failures.push(`missing service: ${service}`);
                    }
                }
                for (const service of ["mail.store", "mail.chat_hub"]) {
                    if (service in services) {
                        failures.push(`unexpected service: ${service}`);
                    }
                }
                if (!mainComponents.contains("OverlayContainer")) {
                    failures.push("missing main component: OverlayContainer");
                }
                if (mainComponents.contains("mail.ChatHub")) {
                    failures.push("unexpected main component: mail.ChatHub");
                }
                if (odoo.loader.modules.has("@mail/core/common/chat_hub")) {
                    failures.push("unexpected module: @mail/core/common/chat_hub");
                }
                if (document.querySelector(".o-mail-ChatHub, .o-mail-ChatBubble")) {
                    failures.push("unexpected Mail ChatHub DOM");
                }
                root._handleImportFile("not JSON");
                requestAnimationFrame(() => requestAnimationFrame(() => {
                    const dialog = document.querySelector(".o_dialog");
                    if (!dialog) {
                        failures.push("import validation dialog did not render");
                    }
                    dialog?.querySelector(".btn-secondary")?.click();
                    if (failures.length) {
                        throw new Error(failures.join("; "));
                    }
                    console.log("test successful");
                }));
            """,
        )
