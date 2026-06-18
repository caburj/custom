/** @odoo-module **/

import { after, describe, destroy, expect, getFixture, test } from "@odoo/hoot";
import { Component, mount, plugin, props, types as t, xml } from "@odoo/owl";
import { animationFrame } from "@odoo/hoot-mock";
import { AiDebugStore } from "@ai_debug/store";

// -- Fake fields_get results for two related models -------------------------

const THREAD_FIELDS = {
    id: { type: "integer" },
    name: { type: "char" },
    loop_ids: {
        type: "one2many",
        relation: "ai.debug.loop",
        relation_field: "thread_id",
    },
};

const LOOP_FIELDS = {
    id: { type: "integer" },
    thread_id: {
        type: "many2one",
        relation: "ai.debug.thread",
    },
    label: { type: "char" },
};

// -- Test component that renders a one2many count ---------------------------

class LoopCounter extends Component {
    static template = xml`
        <div>
            <span class="count" t-out="this.loops.length"/>
            <t t-foreach="this.loops" t-as="loop" t-key="loop.id">
                <span class="loop-label" t-out="loop.label"/>
            </t>
        </div>
    `;
    props = props({ threadId: t.number() });

    store = plugin(AiDebugStore);

    get loops() {
        const thread = this.store.get("ai.debug.thread", this.props.threadId);
        return thread ? thread.loop_ids : [];
    }
}

/**
 * Mount LoopCounter with the AiDebugStore plugin registered.
 * Returns the mounted component instance; access store via component.store.
 */
async function mountComponent(props) {
    const fixture = getFixture();
    const component = await mount(LoopCounter, fixture, {
        props,
        plugins: [AiDebugStore],
        test: true,
    });
    after(() => destroy(component));
    // Register model schemas so insert() and getBy() work correctly.
    component.store.registerModel("ai.debug.thread", THREAD_FIELDS, "-id");
    component.store.registerModel("ai.debug.loop", LOOP_FIELDS, "id");
    return component;
}

// ---------------------------------------------------------------------------

describe("Store: derived one2many reactivity", () => {
    function makeStore() {
        const store = new AiDebugStore();
        store.registerModel("ai.debug.thread", THREAD_FIELDS, "-id");
        store.registerModel("ai.debug.loop", LOOP_FIELDS, "id");
        return store;
    }

    test("getBy returns children linked via many2one", () => {
        const store = makeStore();
        store.insert("ai.debug.thread", { id: 1, name: "T1" });
        store.insert("ai.debug.loop", { id: 10, thread_id: 1, label: "L1" });
        store.insert("ai.debug.loop", { id: 11, thread_id: 1, label: "L2" });

        const thread = store.get("ai.debug.thread", 1);
        const loops = thread.loop_ids;
        expect(loops.length).toBe(2);
        expect(loops[0].label).toBe("L1");
        expect(loops[1].label).toBe("L2");
    });

    test("one2many returns empty when no children exist", () => {
        const store = makeStore();
        store.insert("ai.debug.thread", { id: 1, name: "T1" });

        const thread = store.get("ai.debug.thread", 1);
        expect(thread.loop_ids.length).toBe(0);
    });

    test("inserting a child reactively updates component reading parent one2many", async () => {
        // Mount first (no records yet); thread=1 doesn't exist so loops=[].
        const component = await mountComponent({ threadId: 1 });
        const store = component.store;

        // Insert thread and await a frame so the component sees it.
        store.insert("ai.debug.thread", { id: 1, name: "T1" });
        await animationFrame();

        // Initially no loops
        expect(".count").toHaveText("0");

        // Insert a child loop pointing at thread 1
        store.insert("ai.debug.loop", { id: 10, thread_id: 1, label: "First" });
        await animationFrame();

        expect(".count").toHaveText("1");
        expect(".loop-label").toHaveText("First");

        // Insert another
        store.insert("ai.debug.loop", { id: 11, thread_id: 1, label: "Second" });
        await animationFrame();

        expect(".count").toHaveText("2");
    });

    test("inserting child for different parent does not affect first parent", async () => {
        const component = await mountComponent({ threadId: 1 });
        const store = component.store;

        // Insert both threads; component watches thread 1.
        store.insert("ai.debug.thread", { id: 1, name: "T1" });
        store.insert("ai.debug.thread", { id: 2, name: "T2" });
        await animationFrame();

        expect(".count").toHaveText("0");

        // Insert a loop for thread 2 — thread 1 counter should stay at 0
        store.insert("ai.debug.loop", { id: 10, thread_id: 2, label: "Other" });
        await animationFrame();

        expect(".count").toHaveText("0");
    });
});
