/** @odoo-module **/

import { Component, onWillUnmount, plugin, proxy, signal, useEffect, props, types as t } from "@odoo/owl";
import { JsonViewer } from "@ai_debug/components/json_viewer";
import { formatDuration } from "@ai_debug/components/format";
import { AiDebugStore } from "@ai_debug/store";

export class ToolCallCard extends Component {
    static template = "ai_debug.ToolCallCard";
    static components = { JsonViewer };
    props = props({
        toolCall: t.object(),
    });

    store = plugin(AiDebugStore);

    setup() {
        this.state = proxy({ expanded: true });
        this.rootRef = signal(null);

        // When the store flags this card as the focus target, scroll it
        // into the vertical center of the conversation panel. Parents
        // (LoopDetailStrip, IterationSection) handle their own auto-expand
        // effects, so by the time we get a frame the card is in the DOM.
        useEffect(() => {
            const focusId = this.store.focusToolCallId();
            // touch focusNonce so a repeated focus on the same id re-fires
            this.store.focusNonce();
            if (focusId !== this.props.toolCall.id) {
                // Focus moved off this card: cancel any armed
                // focus-landing observer/timer so we don't release
                // sentinel suppression for a stale target.
                this._cancelFocusLanding();
                return;
            }
            this._focusSelf();
        });

        // Clean up any armed observer / timer if the card is unmounted
        // mid-flight (e.g. thread switch right after a click).
        onWillUnmount(() => this._cancelFocusLanding());
    }

    _focusSelf() {
        // Two RAFs: first lets parent t-if expansions render, second lets
        // layout settle so getBoundingClientRect returns post-expand values.
        requestAnimationFrame(() => requestAnimationFrame(() => {
            const el = this.rootRef();
            if (!el) return;

            // Scroll within the nearest scrollable ancestor, not the page.
            const container = el.closest(".conversation-view");
            if (container) {
                const containerRect = container.getBoundingClientRect();
                const elRect = el.getBoundingClientRect();
                const target = container.scrollTop
                    + (elRect.top - containerRect.top)
                    - (containerRect.height / 2)
                    + (elRect.height / 2);
                container.scrollTo({ top: Math.max(0, target), behavior: "smooth" });
            }

            this._releaseFocusOnLanding(el, container);
        }));
    }

    /**
     * Release the store's sentinel suppression (store.endFocus()) once
     * this card is actually visible (>=50%) in the conversation-view --
     * i.e. the smooth-scroll has effectively landed, so further sentinel
     * fetches can't misplace it. A 2s safety timeout releases
     * unconditionally so a layout quirk can't leave pagination disabled.
     */
    _releaseFocusOnLanding(el, container) {
        this._cancelFocusLanding();

        const release = () => {
            this.store.endFocus();
            this._cancelFocusLanding();
        };

        this._landingObserver = new IntersectionObserver(
            (entries) => {
                if (entries[0]?.isIntersecting) release();
            },
            { root: container ?? null, threshold: 0.5 },
        );
        this._landingObserver.observe(el);

        this._landingSafety = setTimeout(release, 2000);
    }

    _cancelFocusLanding() {
        this._landingObserver?.disconnect();
        this._landingObserver = null;
        if (this._landingSafety) {
            clearTimeout(this._landingSafety);
            this._landingSafety = null;
        }
    }

    toggleExpanded(ev) {
        this.state.expanded = !this.state.expanded;
        ev.currentTarget.dispatchEvent(new Event("user-toggle", { bubbles: true }));
    }

    openChildLoop(threadId, loopId) {
        const orm = this.env.services?.orm;
        if (!orm) return;
        this.store.focusLoop(orm, threadId, loopId);
    }

    get result() {
        // Odoo's search_read serializes NULL text fields as `false` on the
        // wire, so after a page refresh a yet-unresolved tool call arrives
        // with result=false instead of result=null. Normalize here so both
        // the status icon and the JsonViewer below see a single "empty"
        // sentinel (null) and render the pending state consistently.
        const { result } = this.props.toolCall;
        return result === false ? null : result;
    }

    get statusIcon() {
        const { result } = this;
        if (result === null || result === undefined) {
            return { cls: "running", icon: "fa-spinner spin", label: "running" };
        }
        if (typeof result === "string"
            && (result.startsWith("AccessError") || result.startsWith("Error:"))
        ) {
            return { cls: "error", icon: "fa-times", label: "failed" };
        }
        return { cls: "success", icon: "fa-check", label: "done" };
    }

    formatDuration(ms) {
        return formatDuration(ms);
    }
}
