/** @odoo-module **/

import { after, describe, destroy, expect, getFixture, test } from "@odoo/hoot";
import { Component, mount, props, proxy, signal, types as t, xml } from "@odoo/owl";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { animationFrame } from "@odoo/hoot-mock";
import { useInfiniteScroll } from "@ai_debug/hooks/use_infinite_scroll";

/**
 * Helper: install a fake IntersectionObserver on globalThis.
 * Returns an object with methods to inspect and trigger the observer.
 */
function mockIntersectionObserver() {
    const state = {
        /** @type {Function|null} */
        callback: null,
        /** @type {Element|null} */
        root: null,
        /** @type {Element|null} */
        observedElement: null,
        observeCount: 0,
        disconnectCount: 0,
    };

    class FakeIntersectionObserver {
        constructor(callback, options) {
            state.callback = callback;
            state.root = options?.root ?? null;
        }
        observe(el) {
            state.observedElement = el;
            state.observeCount++;
        }
        unobserve() {}
        disconnect() {
            state.observedElement = null;
            state.disconnectCount++;
        }
    }

    patchWithCleanup(globalThis, { IntersectionObserver: FakeIntersectionObserver });

    return {
        get state() { return state; },
        /** Simulate the sentinel becoming visible. */
        triggerIntersect() {
            state.callback?.([{ isIntersecting: true }]);
        },
        /** Simulate the sentinel leaving the viewport. */
        triggerLeave() {
            state.callback?.([{ isIntersecting: false }]);
        },
    };
}

/**
 * Minimal test component that uses the hook.
 * The sentinel div is conditionally rendered via this.state.showSentinel.
 */
class TestHost extends Component {
    static template = xml`
        <div t-ref="this.scrollRef" style="overflow-y: auto; height: 100px;">
            <div t-ref="this.sentinelRef" t-if="this.state.showSentinel"
                 style="min-height: 1px;" />
            <div style="height: 200px;">content</div>
        </div>
    `;
    props = props({ onIntersect: t.function(), alwaysReconnect: t.boolean().optional() });

    setup() {
        this.scrollRef = signal(null);
        this.sentinelRef = signal(null);
        this.state = proxy({ showSentinel: true });
        useInfiniteScroll({
            scrollRef: this.scrollRef,
            sentinelRef: this.sentinelRef,
            onIntersect: this.props.onIntersect,
            alwaysReconnect: this.props.alwaysReconnect ?? false,
        });
    }
}

/**
 * Mount TestHost without the full Odoo env (no services, no RPCs).
 * Our component is pure OWL — it doesn't need the Odoo service layer.
 */
async function mountTestHost(props) {
    const fixture = getFixture();
    const component = await mount(TestHost, fixture, { props, test: true });
    after(() => destroy(component));
    return component;
}

describe("useInfiniteScroll", () => {

    test("creates IntersectionObserver on mount with correct root", async () => {
        const mock = mockIntersectionObserver();
        let callCount = 0;

        await mountTestHost({ onIntersect: () => callCount++ });

        expect(mock.state.observeCount).toBe(1);
        // root should be the scrollContainer element, not null/viewport
        expect(mock.state.root).not.toBe(null);
        expect(mock.state.root?.style?.overflowY).toBe("auto");
    });

    test("calls onIntersect when sentinel intersects", async () => {
        const mock = mockIntersectionObserver();
        let callCount = 0;

        await mountTestHost({ onIntersect: () => callCount++ });

        expect(callCount).toBe(0);
        mock.triggerIntersect();
        expect(callCount).toBe(1);
    });

    test("does not call onIntersect when sentinel leaves viewport", async () => {
        const mock = mockIntersectionObserver();
        let callCount = 0;

        await mountTestHost({ onIntersect: () => callCount++ });

        mock.triggerLeave();
        expect(callCount).toBe(0);
    });

    test("disconnects observer on unmount", async () => {
        const mock = mockIntersectionObserver();

        const component = await mountTestHost({ onIntersect: () => {} });

        const disconnectsBefore = mock.state.disconnectCount;
        component.__owl__.app.destroy();
        expect(mock.state.disconnectCount).toBeGreaterThan(disconnectsBefore);
    });

    test("default mode: skips reconnect when sentinel element is unchanged", async () => {
        const mock = mockIntersectionObserver();

        const component = await mountTestHost({ onIntersect: () => {} });

        const observeCountAfterMount = mock.state.observeCount;

        // Trigger a re-render without changing the sentinel
        component.render();
        await animationFrame();

        // Should NOT have created a new observer (element unchanged)
        expect(mock.state.observeCount).toBe(observeCountAfterMount);
    });

    test("alwaysReconnect mode: reconnects on every patch", async () => {
        const mock = mockIntersectionObserver();

        const component = await mountTestHost({ onIntersect: () => {}, alwaysReconnect: true });

        const observeCountAfterMount = mock.state.observeCount;

        // Trigger a re-render
        component.render();
        await animationFrame();

        // Should have reconnected even though sentinel element is the same
        expect(mock.state.observeCount).toBeGreaterThan(observeCountAfterMount);
    });

    test("reconnects when sentinel is removed and re-added", async () => {
        const mock = mockIntersectionObserver();

        const component = await mountTestHost({ onIntersect: () => {} });

        const observeCountAfterMount = mock.state.observeCount;

        // Remove sentinel
        component.state.showSentinel = false;
        await animationFrame();

        // Re-add sentinel
        component.state.showSentinel = true;
        await animationFrame();

        expect(mock.state.observeCount).toBeGreaterThan(observeCountAfterMount);
    });
});
