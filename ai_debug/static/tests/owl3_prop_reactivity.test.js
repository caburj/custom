/** @odoo-module **/

import { after, describe, destroy, expect, getFixture, test } from "@odoo/hoot";
import { Component, mount, plugin, props, types as t, xml } from "@odoo/owl";
import { animationFrame } from "@odoo/hoot-mock";
import { AiDebugStore } from "@ai_debug/store";

// Reproduction harness for the OWL-3 reactivity regression at /ai-debug:
// a parent passes a COMPUTED SCALAR prop derived from a store-record getter
// to a child, renders BEFORE the field is in the record's raw (the live
// "insert partial row, then update with the finalized body" path), then the
// field arrives via store.update(). The child must reactively re-render.
//
// This mirrors the real render path:
//   - ConversationView passes content="loop.input_message" to <ChatMessage>
//   - IterationSection passes data="iteration.raw_response" to <JsonViewer>
//     and text="iteration.instructions" to <TextBlock>
//   - ToolCallCard passes data="toolCall.result" to <JsonViewer>
// The recorder inserts a partial row first (ITERATION_STARTED /
// TOOL_CALL_STARTED / NEW_LOOP) and fills the heavy body later via
// store.update() (ITERATION / TOOL_CALL_COMPLETED / LOOP_END).

const LOOP_FIELDS = {
    id: { type: "integer" },
    thread_id: { type: "many2one", relation: "ai.debug.thread" },
    input_message: { type: "text" },
    output_message: { type: "text" },
};

const ITERATION_FIELDS = {
    id: { type: "integer" },
    loop_id: { type: "many2one", relation: "ai.debug.loop" },
    sequence: { type: "integer" },
    instructions: { type: "text" },
    raw_response: { type: "json" },
};

const TOOL_CALL_FIELDS = {
    id: { type: "integer" },
    name: { type: "char" },
    arguments: { type: "json" },
    result: { type: "text" },
};

// -- Minimal faithful children: declare props via the instance-level
//    props({...}) API exactly like ChatMessage / JsonViewer / TextBlock. ----

class Bubble extends Component {
    static template = xml`
        <div>
            <t t-if="this.props.content">
                <span class="bubble-content" t-out="this.props.content"/>
            </t>
            <t t-else="">
                <span class="bubble-empty">No message</span>
            </t>
        </div>`;
    props = props({ content: t.string().optional() });
}

class Viewer extends Component {
    static template = xml`
        <div>
            <t t-if="this.props.data">
                <span class="viewer-data" t-out="this.dataText"/>
            </t>
            <t t-else="">
                <span class="viewer-empty">EMPTY</span>
            </t>
        </div>`;
    props = props({ data: t.any().optional() });
    get dataText() {
        const d = this.props.data;
        return typeof d === "string" ? d : JSON.stringify(d);
    }
}

// Parent reading a loop record and passing a computed scalar prop down,
// shaped like ConversationView's <ChatMessage content="loop.input_message"/>.
class LoopConversation extends Component {
    static template = xml`
        <div>
            <t t-foreach="this.loops" t-as="loop" t-key="loop.id">
                <Bubble content="loop.input_message"/>
            </t>
        </div>`;
    static components = { Bubble };
    props = props({ threadId: t.number() });
    store = plugin(AiDebugStore);
    get loops() {
        const thread = this.store.get("ai.debug.thread", this.props.threadId);
        return thread ? thread.loop_ids : [];
    }
}

// Parent receiving an iteration record as an OBJECT prop (like
// IterationSection) and forwarding scalar fields to leaf children.
class IterSection extends Component {
    static template = xml`
        <div>
            <span class="instr-inline" t-out="this.props.iteration.instructions or 'NO-INSTR'"/>
            <Viewer data="this.props.iteration.raw_response"/>
        </div>`;
    static components = { Viewer };
    props = props({ iteration: t.object() });
}

class IterParent extends Component {
    static template = xml`
        <div>
            <t t-if="this.iteration">
                <IterSection iteration="this.iteration"/>
            </t>
        </div>`;
    static components = { IterSection };
    props = props({ iterationId: t.number() });
    store = plugin(AiDebugStore);
    get iteration() {
        return this.store.get("ai.debug.iteration", this.props.iterationId);
    }
}

class ToolCard extends Component {
    static template = xml`
        <div>
            <span class="tc-name" t-out="this.props.toolCall.name"/>
            <Viewer data="this.props.toolCall.arguments"/>
            <Viewer data="this.props.toolCall.result"/>
        </div>`;
    static components = { Viewer };
    props = props({ toolCall: t.object() });
}

class ToolParent extends Component {
    static template = xml`
        <div>
            <t t-if="this.toolCall">
                <ToolCard toolCall="this.toolCall"/>
            </t>
        </div>`;
    static components = { ToolCard };
    props = props({ toolCallId: t.number() });
    store = plugin(AiDebugStore);
    get toolCall() {
        return this.store.get("ai.debug.tool.call", this.props.toolCallId);
    }
}

async function mountWith(C, props) {
    const fixture = getFixture();
    const component = await mount(C, fixture, { props, plugins: [AiDebugStore], test: true });
    after(() => destroy(component));
    component.store.registerModel("ai.debug.thread", { id: { type: "integer" }, loop_ids: { type: "one2many", relation: "ai.debug.loop", relation_field: "thread_id" } }, "-id");
    component.store.registerModel("ai.debug.loop", LOOP_FIELDS, "id");
    component.store.registerModel("ai.debug.iteration", ITERATION_FIELDS, "id");
    component.store.registerModel("ai.debug.tool.call", TOOL_CALL_FIELDS, "id");
    return component;
}

describe("OWL3 reactivity: computed scalar props from store records", () => {
    test("user bubble: loop.input_message filled via update re-renders the child", async () => {
        const component = await mountWith(LoopConversation, { threadId: 1 });
        const store = component.store;

        // Live order: NEW_LOOP inserts a partial loop (no input_message yet),
        // then LOOP_END fills it via store.update.
        store.insert("ai.debug.thread", { id: 1 });
        store.insert("ai.debug.loop", { id: 10, thread_id: 1 });
        await animationFrame();

        expect(".bubble-empty").toHaveCount(1);
        expect(".bubble-content").toHaveCount(0);

        store.update("ai.debug.loop", 10, { input_message: "Hello agent" });
        await animationFrame();

        expect(".bubble-content").toHaveText("Hello agent");
        expect(".bubble-empty").toHaveCount(0);
    });

    test("iteration tab: raw_response filled via update re-renders JsonViewer", async () => {
        const component = await mountWith(IterParent, { iterationId: 20 });
        const store = component.store;

        // ITERATION_STARTED: partial row (instructions captured, body not yet).
        store.insert("ai.debug.iteration", { id: 20, loop_id: 1, sequence: 1, instructions: "SYS" });
        await animationFrame();

        expect(".instr-inline").toHaveText("SYS");
        expect(".viewer-empty").toHaveCount(1);

        // ITERATION: finalize with the raw_response body.
        store.update("ai.debug.iteration", 20, { raw_response: { ok: true } });
        await animationFrame();

        expect(".viewer-data").toHaveText('{"ok":true}');
    });

    test("tool call: result filled via update re-renders JsonViewer", async () => {
        const component = await mountWith(ToolParent, { toolCallId: 30 });
        const store = component.store;

        // TOOL_CALL_STARTED: name + arguments present, result still pending.
        store.insert("ai.debug.tool.call", { id: 30, name: "read_group", arguments: { model: "res.partner" } });
        await animationFrame();

        expect(".tc-name").toHaveText("read_group");
        // arguments present at first render -> renders fine (control).
        expect(".viewer-data").toHaveCount(1);

        // TOOL_CALL_COMPLETED: result arrives via update.
        store.update("ai.debug.tool.call", 30, { result: "42 rows" });
        await animationFrame();

        expect(".viewer-data").toHaveCount(2);
        expect(".viewer-data:last").toHaveText("42 rows");
    });
});
