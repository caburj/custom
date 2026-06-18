/** @odoo-module **/

import { describe, expect, test } from "@odoo/hoot";
import { reconstructMessagesSent } from "@ai_debug/components/messages_reconstruction";

describe("reconstructMessagesSent", () => {
    test("returns a single iteration's own delta when alone in the loop", () => {
        const it = { sequence: 1, messages_delta: [{ role: "user", content: "hi" }] };
        it.loop_id = { iteration_ids: [it] };
        expect(reconstructMessagesSent(it)).toEqual([{ role: "user", content: "hi" }]);
    });

    test("concatenates deltas up to and including the target iteration", () => {
        const it1 = { sequence: 1, messages_delta: [
            { role: "system", content: "S" },
            { role: "user", content: "U" },
            { role: "assistant", content: "A1" },
        ] };
        const it2 = { sequence: 2, messages_delta: [
            { role: "tool", content: "T1" },
            { role: "assistant", content: "A2" },
        ] };
        const it3 = { sequence: 3, messages_delta: [
            { role: "tool", content: "T2" },
            { role: "assistant", content: "A3" },
        ] };
        const loop = { iteration_ids: [it1, it2, it3] };
        it1.loop_id = it2.loop_id = it3.loop_id = loop;

        expect(reconstructMessagesSent(it1)).toEqual([
            { role: "system", content: "S" },
            { role: "user", content: "U" },
            { role: "assistant", content: "A1" },
        ]);
        expect(reconstructMessagesSent(it2)).toEqual([
            { role: "system", content: "S" },
            { role: "user", content: "U" },
            { role: "assistant", content: "A1" },
            { role: "tool", content: "T1" },
            { role: "assistant", content: "A2" },
        ]);
        expect(reconstructMessagesSent(it3)).toEqual([
            { role: "system", content: "S" },
            { role: "user", content: "U" },
            { role: "assistant", content: "A1" },
            { role: "tool", content: "T1" },
            { role: "assistant", content: "A2" },
            { role: "tool", content: "T2" },
            { role: "assistant", content: "A3" },
        ]);
    });

    test("ignores siblings with sequence greater than target (stops at target)", () => {
        const it1 = { sequence: 1, messages_delta: [{ role: "user", content: "U" }] };
        const it2 = { sequence: 2, messages_delta: [{ role: "assistant", content: "A" }] };
        const it3 = { sequence: 3, messages_delta: [{ role: "tool", content: "T" }] };
        const loop = { iteration_ids: [it1, it2, it3] };
        it1.loop_id = it2.loop_id = it3.loop_id = loop;
        expect(reconstructMessagesSent(it1)).toEqual([{ role: "user", content: "U" }]);
    });

    test("skips siblings with null/undefined messages_delta", () => {
        const it1 = { sequence: 1, messages_delta: null };
        const it2 = { sequence: 2, messages_delta: [{ role: "assistant", content: "A" }] };
        const loop = { iteration_ids: [it1, it2] };
        it1.loop_id = it2.loop_id = loop;
        expect(reconstructMessagesSent(it2)).toEqual([{ role: "assistant", content: "A" }]);

        // Target itself has null delta — should still reconstruct correctly from predecessors
        const it3 = { sequence: 3, messages_delta: null };
        const loopWithNullTarget = { iteration_ids: [it2, it3] };
        it2.loop_id = loopWithNullTarget;
        it3.loop_id = loopWithNullTarget;
        expect(reconstructMessagesSent(it3)).toEqual([{ role: "assistant", content: "A" }]);
    });

    test("returns empty array when loop_id or iteration_ids is missing", () => {
        expect(reconstructMessagesSent({ sequence: 1 })).toEqual([]);
        expect(reconstructMessagesSent({ sequence: 1, loop_id: {} })).toEqual([]);
    });
});
