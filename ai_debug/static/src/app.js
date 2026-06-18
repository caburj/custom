/** @odoo-module **/

import { Component, onWillUnmount, plugin, proxy, useEffect } from "@odoo/owl";
import { MainComponentsContainer } from "@web/core/main_components_container";
import { ThreadSidebar } from "@ai_debug/components/thread_sidebar";
import { ConversationView } from "@ai_debug/components/conversation_view";
import { ThreadBreadcrumbs } from "@ai_debug/components/thread_breadcrumbs";
import { ExportButton } from "@ai_debug/components/import_export_bar";
import { ImportedBanner } from "@ai_debug/components/imported_banner";
import { AiDebugStore } from "@ai_debug/store";

const DEFAULT_WIDTH = 280;
const MIN_WIDTH = 140;

const LS = {
    getBool: (key, fallback) => {
        const v = localStorage.getItem(key);
        return v === null ? fallback : v !== "false";
    },
    getInt: (key, fallback) => {
        const v = parseInt(localStorage.getItem(key));
        return isNaN(v) ? fallback : v;
    },
};

export class AiDebugApp extends Component {
    static template = "ai_debug.App";
    static components = { ThreadSidebar, ConversationView, ThreadBreadcrumbs, ExportButton, ImportedBanner, MainComponentsContainer };

    // Resolve the store as a plugin. The class-field initializer runs at
    // construction time -- before setup() -- so providePlugins() inside
    // setup() would be too late: the plugin lookup would throw "Unknown
    // plugin". Instead AiDebugStore is registered into the shared ``services``
    // Resource in start.js, so the App provides it (with every framework
    // service-plugin) before this class field is initialized.
    store = plugin(AiDebugStore);

    sidebar = proxy({
        collapsed: LS.getBool("ai_debug_sidebar_collapsed", false),
        width: LS.getInt("ai_debug_sidebar_width", DEFAULT_WIDTH),
    });

    setup() {
        const { bus_service, orm } = this.env.services;
        this.orm = orm;

        const guardLive = (handler) => (payload) => {
            if (this.store.isImported()) return;
            handler(payload);
        };

        this.store.init(orm);
        // The boot chain is async; a user can click Import at any await
        // boundary. Re-check ``isImported`` after each await so live
        // fetches don't mix into / overwrite the imported view.
        this.store.loadFromServer(orm).then(async () => {
            if (this.store.isImported()) return;
            await this.store.fetchThreads(orm, { limit: 10 });
            if (this.store.isImported()) return;
            const firstThread = this.store.getRootThreads()[0];
            if (firstThread) {
                this.store.selectThread(firstThread.id);
            }
        });

        bus_service.subscribe("AI_DEBUG_NEW_THREAD", guardLive((payload) => {
            const { agent_name, user_name, ...rest } = payload;
            this.store.insert("ai.debug.thread", {
                ...rest,
                agent_id: payload.agent_id ? [payload.agent_id, agent_name || ""] : false,
                user_id: payload.user_id ? [payload.user_id, user_name || ""] : false,
            });
            this.store.applyDefaultCollapse(payload);
            this.store.threadCount.set(this.store.threadCount() + 1);
            // Only auto-select if it's a root thread (child threads appear in the tree under their parent)
            if (!payload.parent_thread_id) {
                this.store.selectedThreadId.set(payload.id);
            }
        }));
        bus_service.subscribe("AI_DEBUG_NEW_LOOP", guardLive((payload) => {
            // ``is_background`` belongs on the THREAD, not the loop -- pull it
            // out of the spread so it doesn't land on the loop Record.
            const { agent_name, is_background, ...rest } = payload;
            this.store.insert("ai.debug.loop", {
                ...rest,
                agent_id: payload.agent_id ? [payload.agent_id, agent_name || ""] : false,
            });
            const thread = this.store.get("ai.debug.thread", payload.thread_id);
            if (thread) {
                // Bump loop_count and re-sync the thread's run mode: a session
                // continued in a different mode (bg<->fg) flips is_background,
                // so the node's flag tracks the latest turn.
                this.store.update("ai.debug.thread", payload.thread_id, {
                    loop_count: (thread.loop_count || 0) + 1,
                    is_background: Boolean(is_background),
                });
            }
        }));
        bus_service.subscribe("AI_DEBUG_ITERATION_STARTED", guardLive((payload) => {
            // Pending row created the moment the LLM HTTP request is
            // dispatched. Renders as a spinner until AI_DEBUG_ITERATION
            // flips is_running to false with the completed metrics.
            this.store.insert("ai.debug.iteration", payload);
        }));
        bus_service.subscribe("AI_DEBUG_ITERATION", guardLive((payload) => {
            // The iteration carries only ``available_tool_ids`` (list of ints);
            // the referenced ``ir.actions.server`` rows are lazy-loaded by
            // the "Available Tools" tab via ``store.ensureLazyField``.
            //
            // When AI_DEBUG_ITERATION_STARTED arrived first for the same id,
            // update preserves the existing Record proxy so any mounted
            // IterationSection stays reactive on the transition.
            if (this.store.get("ai.debug.iteration", payload.id)) {
                this.store.update("ai.debug.iteration", payload.id, payload);
            } else {
                this.store.insert("ai.debug.iteration", payload);
            }
            if (payload.tokens_in || payload.tokens_out) {
                const iterations = this.store.getBy(
                    "ai.debug.iteration", "loop_id", payload.loop_id
                );
                this.store.update("ai.debug.loop", payload.loop_id, {
                    tokens_in: iterations.reduce((s, it) => s + (it.tokens_in || 0), 0),
                    tokens_out: iterations.reduce((s, it) => s + (it.tokens_out || 0), 0),
                });
            }
        }));
        bus_service.subscribe("AI_DEBUG_TOOL_CALL_STARTED", guardLive((payload) => {
            const { tool_name, ...rest } = payload;
            this.store.insert("ai.debug.tool.call", {
                ...rest,
                tool_id: payload.tool_id ? [payload.tool_id, tool_name || ""] : false,
            });
        }));
        bus_service.subscribe("AI_DEBUG_TOOL_CALL_COMPLETED", guardLive((payload) => {
            this.store.update("ai.debug.tool.call", payload.id, payload);
        }));
        bus_service.subscribe("AI_DEBUG_LOOP_END", guardLive((payload) => {
            const { thread_name, ...loopFields } = payload;
            this.store.update("ai.debug.loop", payload.id, loopFields);
            if (thread_name && payload.thread_id) {
                this.store.update("ai.debug.thread", payload.thread_id, {
                    name: thread_name,
                });
            }
        }));

        useEffect(() => {
            document.body.classList.toggle("imported-mode", this.store.isImported());
            return () => document.body.classList.remove("imported-mode");
        });

        this.setTheme(localStorage.getItem("ai_debug_theme") || "dark");

        // 1Hz wall-clock tick driving the sidebar's per-thread elapsed-time
        // labels. Cheap unconditionally: components only subscribe to
        // ``store.now`` when they have a running loop, so idle dashboards
        // don't re-render every second.
        const tickHandle = setInterval(() => {
            this.store.now.set(Date.now());
        }, 1000);
        onWillUnmount(() => clearInterval(tickHandle));
    }

    get selectedThread() {
        const selId = this.store.selectedThreadId();
        if (!selId) return null;
        return this.store.get("ai.debug.thread", selId);
    }

    setTheme(theme) {
        document.body.setAttribute("theme", theme);
        localStorage.setItem("ai_debug_theme", theme);
        this._theme = theme;
    }

    toggleTheme() {
        this.setTheme(this._theme === "dark" ? "light" : "dark");
    }

    toggleSidebar() {
        this.sidebar.collapsed = !this.sidebar.collapsed;
        if (!this.sidebar.collapsed) {
            this.sidebar.width = DEFAULT_WIDTH;
            localStorage.setItem("ai_debug_sidebar_width", DEFAULT_WIDTH);
        }
        localStorage.setItem("ai_debug_sidebar_collapsed", this.sidebar.collapsed);
    }

    startResize(ev) {
        ev.preventDefault();
        const startX = ev.clientX;
        const startWidth = this.sidebar.width;
        const onMove = (e) => {
            const newWidth = startWidth + (e.clientX - startX);
            if (newWidth < MIN_WIDTH) {
                this.sidebar.collapsed = true;
            } else {
                this.sidebar.collapsed = false;
                this.sidebar.width = Math.max(MIN_WIDTH, Math.min(560, newWidth));
            }
        };
        const onUp = () => {
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
            localStorage.setItem("ai_debug_sidebar_width", this.sidebar.width);
            localStorage.setItem("ai_debug_sidebar_collapsed", this.sidebar.collapsed);
        };
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
    }

    onSelectThread(threadId) {
        this.store.selectThread(threadId);
    }
}
