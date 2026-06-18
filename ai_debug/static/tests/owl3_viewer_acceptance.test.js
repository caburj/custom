/** @odoo-module **/

// ---------------------------------------------------------------------------
// ACCEPTANCE suite for the /ai-debug OWL-3 reactivity requirement.
//
// Requirement (the contract, from the user-visible symptoms — NOT the diff):
// At /ai-debug, after the async fetch_loops/bus update path resolves:
//   1. A user-message bubble renders its real content (NOT "No message").
//   2. An iteration's tabs render populated data: Tool Calls (card ARGUMENTS +
//      RESULT), System Prompt, Messages Sent, Raw Request, Raw Response.
//
// These tests mount the REAL production viewer components (ConversationView,
// ChatMessage, IterationSection, ToolCallCard, JsonViewer, TextBlock) wired to
// a REAL AiDebugStore, and drive data through the REAL live path that triggers
// the bug: store.insert a PARTIAL record (no heavy body), render, then
// store.update the body fields later — mirroring app.js's bus handlers
// (NEW_LOOP→LOOP_END, ITERATION_STARTED→ITERATION,
// TOOL_CALL_STARTED→TOOL_CALL_COMPLETED). They assert on the rendered DOM the
// user sees, referencing no implementation internals.
//
// The components are mounted in the PRODUCTION runtime configuration — OWL
// dev mode OFF (`test: false`), exactly as the live /ai-debug page runs — so
// the assertions reflect what a real user sees, not a dev-only artifact.
// The final describe block additionally guards the dev-mode-validation facet
// (`test: true`), which the web client runs in debug mode.
// ---------------------------------------------------------------------------

import { after, describe, destroy, expect, getFixture, test } from "@odoo/hoot";
import { Component, mount, plugin, props, types as t, xml } from "@odoo/owl";
import { animationFrame } from "@odoo/hoot-mock";
import { getTemplate } from "@web/core/templates";
import { AiDebugStore } from "@ai_debug/store";
import { ChatMessage } from "@ai_debug/components/chat_message";
import { ConversationView } from "@ai_debug/components/conversation_view";
import { IterationSection } from "@ai_debug/components/iteration_section";

// Minimal env: the services any component in these mount trees resolves —
// "dialog" (JsonViewer / TextBlock) and "popover" (the stock CopyButton's
// usePopover, which renders inside ChatMessage / JsonViewer / TextBlock once
// their content prop actually binds). Both are exercised on click, never
// during the render under test.
const ENV = {
    services: {
        dialog: { add: () => () => {} },
        popover: { add: () => () => {} },
    },
};

const THREAD_FIELDS = {
    id: { type: "integer" },
    loop_count: { type: "integer" },
    parent_thread_id: { type: "many2one", relation: "ai.debug.thread" },
    user_id: { type: "many2one", relation: "res.users" },
    loop_ids: { type: "one2many", relation: "ai.debug.loop", relation_field: "thread_id" },
};
const LOOP_FIELDS = {
    id: { type: "integer" },
    thread_id: { type: "many2one", relation: "ai.debug.thread" },
    input_message: { type: "text" },
    input_message_html: { type: "html" },
    output_message: { type: "text" },
    is_running: { type: "boolean" },
    termination_reason: { type: "char" },
    agent_id: { type: "many2one", relation: "ai.agent" },
    model_name: { type: "char" },
    parent_tool_call_id: { type: "many2one", relation: "ai.debug.tool.call" },
};
const ITERATION_FIELDS = {
    id: { type: "integer" },
    loop_id: { type: "many2one", relation: "ai.debug.loop" },
    sequence: { type: "integer" },
    instructions: { type: "text" },
    output_message: { type: "text" },
    messages_sent: { type: "json" },
    raw_request: { type: "json" },
    raw_response: { type: "json" },
    is_running: { type: "boolean" },
    available_tool_ids: { type: "many2many", relation: "ir.actions.server" },
    tool_call_ids: { type: "one2many", relation: "ai.debug.tool.call", relation_field: "iteration_id" },
    tokens_in: { type: "integer" },
    tokens_out: { type: "integer" },
    tokens_cached: { type: "integer" },
    duration_ms: { type: "integer" },
};
const TOOL_CALL_FIELDS = {
    id: { type: "integer" },
    iteration_id: { type: "many2one", relation: "ai.debug.iteration" },
    name: { type: "char" },
    arguments: { type: "json" },
    result: { type: "text" },
    refused: { type: "boolean" },
    triggered_confirmation: { type: "boolean" },
    child_loop_ids: { type: "one2many", relation: "ai.debug.loop", relation_field: "parent_tool_call_id" },
    duration_ms: { type: "integer" },
};

function registerAll(store) {
    store.registerModel("ai.debug.thread", THREAD_FIELDS, "-id");
    store.registerModel("ai.debug.loop", LOOP_FIELDS, "id");
    store.registerModel("ai.debug.iteration", ITERATION_FIELDS, "sequence");
    store.registerModel("ai.debug.tool.call", TOOL_CALL_FIELDS, "id");
    store.registerModel("ir.actions.server", { id: { type: "integer" } }, "id");
}

// Mount a component the way the live /ai-debug page runs it: dev mode OFF,
// real named templates resolved from the registry, real AiDebugStore plugin.
async function mountProd(C, componentProps) {
    const fixture = getFixture();
    const component = await mount(C, fixture, {
        props: componentProps,
        env: ENV,
        getTemplate,
        plugins: [AiDebugStore],
        test: false,
    });
    after(() => destroy(component));
    return component;
}

const STUB_ORM = { call: async () => ({ loops: [], iterations: [], tool_calls: [] }) };

// ===========================================================================
// REQUIREMENT — the real viewer components must render real content after the
// live insert-partial-then-update path resolves.
// ===========================================================================
describe("Acceptance: /ai-debug renders real content after the live update path", () => {
    test("user-message bubble shows its real content (ConversationView + ChatMessage)", async () => {
        // ConversationView passes content="loop.input_message_html or
        // loop.input_message" to the real ChatMessage. Source the thread from
        // the store plugin so the o2m loop list is reactive.
        class CVHarness extends Component {
            static template = xml`<ConversationView thread="this.thread" orm="this.orm"/>`;
            static components = { ConversationView };
            store = plugin(AiDebugStore);
            orm = STUB_ORM;
            get thread() { return this.store.get("ai.debug.thread", 1); }
        }
        const h = await mountProd(CVHarness, {});
        registerAll(h.store);

        // Live order: NEW_LOOP inserts a partial loop (no message body yet) …
        h.store.insert("ai.debug.thread", { id: 1, user_id: [1, "Me"] });
        h.store.insert("ai.debug.loop", { id: 10, thread_id: 1, is_running: false });
        await animationFrame();

        // … then LOOP_END fills the body via store.update.
        h.store.update("ai.debug.loop", 10, { input_message: "Hello agent" });
        await animationFrame();

        // The user bubble must now show the real content (requirement #1).
        expect(".chat-message-user .chat-bubble").toHaveText("Hello agent");
    });

    test("iteration Raw Response tab shows its data (IterationSection + JsonViewer)", async () => {
        class IterHarness extends Component {
            static template = xml`<div><t t-if="this.iter"><IterationSection iteration="this.iter" total="1"/></t></div>`;
            static components = { IterationSection };
            store = plugin(AiDebugStore);
            get iter() { return this.store.get("ai.debug.iteration", 20); }
        }
        const h = await mountProd(IterHarness, {});
        registerAll(h.store);

        // ITERATION_STARTED: partial iteration (no raw_response body yet).
        h.store.insert("ai.debug.iteration", { id: 20, loop_id: 1, sequence: 1, instructions: "SYS", is_running: false });
        await animationFrame();

        // Open the iteration and switch to the Raw Response tab while the body
        // is still absent (the read that the bug must make reactive).
        getFixture().querySelector(".iteration-header").click();
        await animationFrame();
        const respTab = [...getFixture().querySelectorAll(".iter-tab")]
            .find((b) => b.textContent.trim().startsWith("Raw Response"));
        respTab.click();
        await animationFrame();

        // ITERATION: finalize with the raw_response body via store.update.
        h.store.update("ai.debug.iteration", 20, { raw_response: { ok: true } });
        await animationFrame();

        // The Raw Response tab must now render the JSON reactively (req #2).
        // JsonViewer renders an object's root node collapsed by default, so the
        // bound object surfaces as the "{1 keys}" summary; expanding it proves
        // the populated value ("ok": true) actually reached the component.
        expect(".iter-tab-content .jv-root").toHaveCount(1);
        getFixture().querySelector(".iter-tab-content .jv-root .ai-json-toggle").click();
        await animationFrame();
        expect(".iter-tab-content .jv-root").toHaveText(/ok/);
        expect(".iter-tab-content .jv-root").toHaveText(/true/);
    });

    test("tool-call card shows ARGUMENTS and RESULT (IterationSection + ToolCallCard + JsonViewer)", async () => {
        class IterHarness extends Component {
            static template = xml`<div><t t-if="this.iter"><IterationSection iteration="this.iter" total="1"/></t></div>`;
            static components = { IterationSection };
            store = plugin(AiDebugStore);
            get iter() { return this.store.get("ai.debug.iteration", 20); }
        }
        const h = await mountProd(IterHarness, {});
        registerAll(h.store);

        h.store.insert("ai.debug.iteration", { id: 20, loop_id: 1, sequence: 1, instructions: "SYS", is_running: false });
        // TOOL_CALL_STARTED: name + arguments present, result still pending.
        h.store.insert("ai.debug.tool.call", { id: 30, iteration_id: 20, name: "read_group", arguments: { model: "res.partner" } });
        await animationFrame();

        // Open the iteration (Tool Calls is the default tab; the card body is
        // expanded by default).
        getFixture().querySelector(".iteration-header").click();
        await animationFrame();

        // ARGUMENTS are present from the first render -> must render now.
        const argsSection = [...getFixture().querySelectorAll(".tool-call-section")]
            .find((s) => s.querySelector(".tool-call-section-label")?.textContent.includes("Arguments"));
        expect(argsSection.querySelector(".jv-root")).not.toBe(null);
        expect(argsSection).toHaveText(/res\.partner/);

        // TOOL_CALL_COMPLETED: the result arrives via store.update.
        h.store.update("ai.debug.tool.call", 30, { result: "42 rows" });
        await animationFrame();

        const resultSection = [...getFixture().querySelectorAll(".tool-call-section")]
            .find((s) => s.querySelector(".tool-call-section-label")?.textContent.includes("Result"));
        expect(resultSection).toHaveText(/42 rows/);
    });
});

// ===========================================================================
// ISOLATION — the record.js change makes an absent-then-present record field
// reactive when read through a CORRECTLY-declared scalar prop. This is the
// behaviour the fix claims; it is RED on the base record.js and GREEN on the
// fixed record.js, proving the suite actually exercises the fix (non-vacuous)
// and that the fix's reactivity mechanism is sound in isolation.
// ===========================================================================
describe("Isolation: record-field reactivity through a correctly-declared prop", () => {
    test("a field filled via store.update reactively re-renders the reader", async () => {
        class Bubble extends Component {
            static template = xml`
                <div class="bubble">
                    <t t-if="this.props.content"><span class="bc" t-out="this.props.content"/></t>
                    <t t-else=""><span class="be">No message</span></t>
                </div>`;
            props = props({ content: t.string().optional() });
        }
        class Host extends Component {
            static template = xml`<Bubble content="this.loop ? (this.loop.input_message_html or this.loop.input_message) : undefined"/>`;
            static components = { Bubble };
            store = plugin(AiDebugStore);
            get loop() { return this.store.get("ai.debug.loop", 10); }
        }
        const h = await mountProd(Host, {});
        registerAll(h.store);

        // Partial loop first (no input_message), then fill via update.
        h.store.insert("ai.debug.loop", { id: 10, thread_id: 1 });
        await animationFrame();
        expect(".be").toHaveCount(1);

        h.store.update("ai.debug.loop", 10, { input_message: "Hello agent" });
        await animationFrame();
        expect(".bc").toHaveText("Hello agent");
    });
});

// ===========================================================================
// REGRESSION GUARD for the SECOND defect — the viewer components originally
// declared their optional props with the legacy "key?" optional-suffix
// convention, which OWL 3.0.0-alpha.36 does NOT honour: it treats the literal
// key "content?" as a distinct, required prop, so (a) the real this.props.<key>
// getter never binds even with dev mode off, and (b) the standard odoo hoot
// harness (dev mode ON) rejects the mount with "Invalid component props". The
// fix swept every declaration to `key: t.X().optional()`. This test locks that
// in: the real ChatMessage must now bind this.props.content (rendering the real
// text instead of "No message") AND mount clean under dev-mode validation.
// ===========================================================================
describe("Regression guard: viewer props declared with .optional() under OWL 3", () => {
    test("real ChatMessage binds this.props.content (dev mode off, production runtime)", async () => {
        const fixture = getFixture();
        const c = await mount(ChatMessage, fixture, {
            props: { role: "user", content: "Hi there" },
            env: ENV, getTemplate, test: false,
        });
        after(() => destroy(c));
        // The content prop binds, so the bubble shows the real text, not the
        // "No message" fallback the legacy "content?" declaration produced.
        expect(c.props.content).toBe("Hi there");
        expect(fixture.querySelector(".chat-bubble")).toHaveText("Hi there");
    });

    test("real ChatMessage mounts clean under dev-mode prop validation", async () => {
        // test:true forces OWL dev mode on -> the same prop validation the web
        // client runs in debug mode. With the legacy "content?" declaration this
        // threw "Invalid component props … missingKeys:['content?', …]"; with the
        // .optional() sweep it must mount clean.
        let message = "MOUNTED-CLEAN";
        let component = null;
        try {
            const fixture = getFixture();
            component = await mount(ChatMessage, fixture, {
                props: { role: "user", content: "Hi" },
                env: ENV, getTemplate, test: true,
            });
        } catch (e) {
            message = String(e.message || e);
        }
        if (component) {
            after(() => destroy(component));
        }
        expect(message).toBe("MOUNTED-CLEAN");
    });
});
