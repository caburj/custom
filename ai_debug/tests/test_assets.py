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
                requestAnimationFrame(() => requestAnimationFrame(async () => {
                    const dialog = document.querySelector(".o_dialog");
                    if (!dialog) {
                        failures.push("import validation dialog did not render");
                    }
                    dialog?.querySelector(".btn-secondary")?.click();
                    const traceId = "usage-runtime-check";
                    root._onTraceEvent({ type: "new_trace", trace_id: traceId, root_session_id: 10,
                        channel_id: 42, channel_name: "Audit conversation" });
                    root._onTraceEvent({
                        type: "iteration", trace_id: traceId, iteration_id: "usage-round",
                        phase: "prepared", iteration_index: 1,
                    });
                    root._onTraceEvent({
                        type: "iteration", trace_id: traceId, iteration_id: "usage-round",
                        phase: "result_received", provider: "google",
                        usage: {
                            input: 120, cached_input: 40,
                            output: { text: 25, image: 0 }, thought: 5,
                        },
                        cost: 0.00234, duration_ms: 1200, duration_kind: "model_round_trip",
                    });
                    root._onTraceEvent({
                        type: "request_state", trace_id: traceId, iteration_id: "usage-round",
                        phase: "result_consumed",
                    });
                    root._onTraceEvent({
                        type: "loop_end", trace_id: traceId, termination_reason: "success",
                        duration_ms: 6000, duration_kind: "exchange_elapsed",
                    });
                    const { loadAllTraces } = odoo.loader.modules.get("@ai_debug/app/db");
                    const saved = (await loadAllTraces()).find((trace) => trace.trace_id === traceId);
                    const iteration = saved.iterations[0][1];
                    if (iteration.tokens?.cache_read !== 40 || iteration.tokens.total !== 150
                        || iteration.cost !== 0.00234) {
                        failures.push("captured usage and credits were not persisted");
                    }
                    for (const [id, parentId, parentRound, input, cached, output, cost, elapsed, modelTime] of [
                        ["child", traceId, "usage-round", 60, 20, 15, 0.001, 4000, 2500],
                        ["grandchild", "child", "child-round", 20, 5, 10, 0.0005, 0, 0],
                        ["unrelated", null, null, 1000, 500, 100, 1, 9000, null],
                    ]) {
                        root._onTraceEvent({
                            type: "new_trace", trace_id: id, parent_trace_id: parentId,
                            agent_name: id, parent_request_uuid: parentRound,
                        });
                        root._onTraceEvent({
                            type: "iteration", trace_id: id, iteration_id: `${id}-round`,
                            iteration_index: 1, phase: "result_received", provider: "openai",
                            usage: {
                                input, cached_input: cached,
                                output: { text: output, image: 0 }, thought: 0,
                            },
                            cost, duration_ms: modelTime, duration_kind: "model_round_trip",
                        });
                        root._onTraceEvent({
                            type: "loop_end", trace_id: id, termination_reason: "success",
                            duration_ms: elapsed, duration_kind: "exchange_elapsed",
                        });
                    }
                    root._onTraceEvent({
                        type: "iteration", trace_id: "child", iteration_id: "pending-round",
                        iteration_index: 2, phase: "prepared",
                    });
                    root._onTraceEvent({
                        type: "new_trace", trace_id: "partial-child", parent_trace_id: "child",
                        parent_request_uuid: "uncaptured-round", agent_name: "Partial child",
                    });
                    const family = root.getTraceFamily(root.traces.get(traceId));
                    const totals = root.getTraceTotals(family);
                    if (family.length !== 4 || totals.total_input !== 200
                        || totals.total_cached !== 65 || totals.total_output !== 55
                        || totals.total_tokens !== 255 || totals.usage_count !== 3
                        || totals.iteration_count !== 4 || totals.cost_count !== 3
                        || Math.abs(totals.total_cost - 0.00384) > 1e-10) {
                        failures.push("exchange total must include children and grandchildren once");
                    }
                    const { hydrateTrace } = odoo.loader.modules.get("@ai_debug/app/trace_store");
                    const familyIds = family.map((trace) => trace.trace_id);
                    const restored = (await loadAllTraces())
                        .filter((trace) => familyIds.includes(trace.trace_id)).map((trace) => hydrateTrace(trace));
                    if (root.getTraceTotals(restored).total_cached !== 65) {
                        failures.push("descendant usage did not survive persistence");
                    }
                    root.selectItem(traceId, "trace");
                    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
                    [...document.querySelectorAll(".o_notebook .nav-link")]
                        .find((tab) => tab.textContent.trim() === "Usage").click();
                    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
                    const summary = document.querySelector(".ai-usage-summary");
                    if (!summary.textContent.includes("Total tokens 255")) {
                        failures.push("exchange total is not visible above the iteration table");
                    }
                    const frame = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
                    const usageButton = (name) => [...document.querySelectorAll(".ai-detail-view button")]
                        .find((button) => button.textContent.trim() === name);
                    const visibleRows = () => [...document.querySelectorAll(".ai-usage-table tbody tr")];
                    const totalCells = [...document.querySelectorAll(".ai-usage-table tfoot td")]
                        .map((cell) => cell.textContent);
                    if (visibleRows().length !== 3 || totalCells.slice(0, 3).join(",") !== "200,65,55"
                        || visibleRows()[2].querySelector("td").textContent !== "80") {
                        failures.push("initial tree must show parent rounds and collapsed child subtotal");
                    }
                    if (totalCells.at(-1) !== "6.0s"
                        || visibleRows().map((row) => row.querySelector("td:last-child").textContent).join(",") !== "6.0s,,4.0s") {
                        failures.push("elapsed time must use each exchange's duration, without adding descendants");
                    }
                    if (totalCells.at(-2) !== ""
                        || visibleRows().map((row) => row.querySelector("td:nth-last-child(2)").textContent).join(",") !== ",1.2s,") {
                        failures.push("model time must appear only on iteration rows");
                    }
                    const roundCredits = visibleRows()[1].querySelectorAll("td")[3].textContent;
                    if (roundCredits.replace(/\\s+/g, "") !== "0.002+0.002subagents"
                        || root.getIterationSubagentCost(root.traces.get(traceId), root.traces.get(traceId).iterations.get("usage-round")) !== 0.0015
                        || root.getIterationSubagentCost(root.traces.get("child"), root.traces.get("child").iterations.get("pending-round")) !== null) {
                        failures.push("iteration credits must separate own cost from recursive subagent cost");
                    }
                    usageButton("Expand all").click();
                    await frame();
                    if (visibleRows().length !== 6
                        || !visibleRows()[4].textContent.includes("grandchild")
                        || visibleRows().some((row) => row.textContent.includes("Partial child") || row.textContent.includes("Iteration 2"))) {
                        failures.push("expanded tree must nest descendants under their initiating rounds");
                    }
                    if (visibleRows()[4].querySelector("td:last-child").textContent !== "0ms") {
                        failures.push("a measured zero elapsed duration must remain visible");
                    }
                    if (visibleRows()[3].querySelector("td:nth-last-child(2)").textContent !== "2.5s"
                        || visibleRows()[5].querySelector("td:nth-last-child(2)").textContent !== "0ms") {
                        failures.push("nested model times must preserve captured zero durations");
                    }
                    const childToggle = document.querySelector('button[aria-label="Collapse child"]');
                    childToggle.click();
                    await frame();
                    if (visibleRows().length !== 3 || childToggle.getAttribute("aria-expanded") !== "false"
                        || !document.querySelector(".ai-usage-summary").textContent.includes("Total tokens 255")) {
                        failures.push("collapsing an agent must preserve exchange totals");
                    }
                    usageButton("Collapse all").click();
                    await frame();
                    if (visibleRows().length !== 1) {
                        failures.push("collapse all must leave the exchange subtotal visible");
                    }
                    root._onTraceEvent({
                        type: "iteration", trace_id: "child", iteration_id: "child-round",
                        phase: "result_received", provider: "openai",
                        usage: { input: 61, cached_input: 20, output: { text: 15, image: 0 }, thought: 0 },
                        cost: 0.001,
                    });
                    await frame();
                    if (visibleRows()[0].querySelector("td").textContent !== "201"
                        || !document.querySelector(".ai-usage-summary").textContent.includes("Total tokens 256")) {
                        failures.push("collapsed subtotals must update when descendant usage arrives");
                    }
                    root.selectItem("child", "trace");
                    await frame();
                    [...document.querySelectorAll(".o_notebook .nav-link")]
                        .find((tab) => tab.textContent.trim() === "Usage").click();
                    await frame();
                    if (!document.querySelector(".ai-usage-summary").textContent.includes("Total tokens 106")
                        || visibleRows().length !== 3 || !visibleRows()[0].textContent.includes("child")) {
                        failures.push("nested exchange must show the same table rooted at that agent");
                    }
                    root.selectItem("unrelated", "trace");
                    await frame();
                    [...document.querySelectorAll(".o_notebook .nav-link")]
                        .find((tab) => tab.textContent.trim() === "Usage").click();
                    await frame();
                    if ([...document.querySelectorAll(".ai-usage-table thead th")]
                        .some((cell) => cell.textContent === "Model time")) {
                        failures.push("model time must be hidden when no durations were captured");
                    }
                    root.selectItem("usage-round", "iteration");
                    await frame();
                    const iterationSummary = document.querySelector(".ai-usage-summary").textContent;
                    if (!iterationSummary.includes("25 text · 5 reasoning")
                        || [...document.querySelectorAll(".o_notebook .nav-link")].some((tab) => tab.textContent.trim() === "Usage")) {
                        failures.push("iteration output must show its breakdown without a Usage tab");
                    }
                    root._onTraceEvent({ type: "new_trace", trace_id: "another-exchange", root_session_id: 11,
                        channel_id: 42, channel_name: "Audit conversation" });
                    root._onTraceEvent({ type: "new_trace", trace_id: "session-only", root_session_id: 12,
                        root_agent_name: "Auditor", channel_id: null });
                    await frame();
                    const headers = [...document.querySelectorAll(".o_ai_debug_group_header")];
                    if (headers.length !== 3
                        || !headers.some((header) => header.textContent.includes("Audit conversation") && header.textContent.includes("Channel #42"))
                        || !headers.some((header) => header.textContent.includes("Auditor") && header.textContent.includes("Session #12"))
                        || root.sidebarNodes.filter((node) => node.id === "group:channel:42").length !== 1) {
                        failures.push("flat headers must group exchanges by channel or root session");
                    }
                    root.state.nestingMode = "lines";
                    await frame();
                    const rowHeight = root.sidebarNodes.reduce((height, node) => height +
                        (node.type === "group" ? 32 : node.type === "trace" ? 44 : 34), 0);
                    if (Number(document.querySelector(".ai-depth-line-svg").getAttribute("height")) !== rowHeight
                        || root.depthLinePaths.some((segment) => segment.d.includes("NaN"))) {
                        failures.push("guide lines must account for section headers");
                    }
                    root.state.nestingMode = "indent";
                    await frame();
                    if (root.sidebarNodes.some((node) => node.type === "trace" &&
                        [traceId, "another-exchange", "session-only"].includes(node.id) && node.depth !== 0)) {
                        failures.push("channel grouping must not add exchange indentation");
                    }
                    if (failures.length) {
                        throw new Error(failures.join("; "));
                    }
                    console.log("test successful");
                }));
            """,
        )
