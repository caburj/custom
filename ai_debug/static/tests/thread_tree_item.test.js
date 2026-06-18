/** @odoo-module **/

import { describe, expect, test } from "@odoo/hoot";
import { ThreadTreeItem } from "@ai_debug/components/thread_tree_item";

// Pin the render-side ordering of subagent threads. The store sorts
// ``ai.debug.thread`` by ``-id`` desc (right for the root-thread feed,
// wrong for sibling subagents); ``orderedChildren`` is the workaround.
// A regression that drops the getter would re-introduce the original bug.

const orderedChildrenGetter = Object.getOwnPropertyDescriptor(
    ThreadTreeItem.prototype, "orderedChildren",
).get;

function call(thread) {
    return orderedChildrenGetter.call({ props: { thread } });
}

describe("ThreadTreeItem.orderedChildren", () => {
    test("sorts child_thread_ids ascending by id (spawn order)", () => {
        const thread = {
            child_thread_ids: [{ id: 102 }, { id: 88 }, { id: 99 }],
        };
        expect(call(thread).map((c) => c.id)).toEqual([88, 99, 102]);
    });

    test("does not mutate the underlying child_thread_ids array", () => {
        const children = [{ id: 102 }, { id: 88 }, { id: 99 }];
        const thread = { child_thread_ids: children };
        call(thread);
        expect(children.map((c) => c.id)).toEqual([102, 88, 99]);
    });

    test("returns an empty array when child_thread_ids is missing", () => {
        expect(call({}).length).toBe(0);
    });

    test("returns an empty array when child_thread_ids is empty", () => {
        expect(call({ child_thread_ids: [] }).length).toBe(0);
    });
});

// The node META line surfaces the session id (always) and a background flag
// (only when the session ran in background). Pin both getters so a regression
// that drops them -- or that shows a mode label on foreground nodes -- is caught.

const sessionIdLabelGetter = Object.getOwnPropertyDescriptor(
    ThreadTreeItem.prototype, "sessionIdLabel",
).get;
const isBackgroundGetter = Object.getOwnPropertyDescriptor(
    ThreadTreeItem.prototype, "isBackground",
).get;

describe("ThreadTreeItem meta line", () => {
    test("sessionIdLabel prefixes the session id with #", () => {
        expect(sessionIdLabelGetter.call({ props: { thread: { session_id: "57" } } })).toBe("#57");
    });

    test("isBackground is true only when the thread ran in background", () => {
        expect(isBackgroundGetter.call({ props: { thread: { is_background: true } } })).toBe(true);
        expect(isBackgroundGetter.call({ props: { thread: { is_background: false } } })).toBe(false);
        // Foreground / imported threads may omit the field entirely.
        expect(isBackgroundGetter.call({ props: { thread: {} } })).toBe(false);
    });
});
