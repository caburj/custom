/** @odoo-module **/
import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class AiDebugApp extends Component {
    static template = "ai_debug.App";
    static props = {};
    static components = {};

    setup() {
        this.busService = useService("bus_service");
        this.state = useState({
            connectionStatus: "connecting",
        });

        this._onWorkerState = ({ detail }) => {
            if (detail === "CONNECTED") {
                this.state.connectionStatus = "connected";
            } else if (detail === "CONNECTING") {
                this.state.connectionStatus = "reconnecting";
            } else {
                this.state.connectionStatus = "disconnected";
            }
        };

        this._onBusNotification = (payload) => {
            console.log(`[ai_debug] ${payload.type}`, payload);
        };

        // Each notification type must be subscribed individually via
        // busService.subscribe(), which listens on the internal notificationBus.
        // busService.addEventListener() only receives connection-level events.
        this._subscribedTypes = ["new_trace", "iteration", "tool_call", "loop_end"];

        onMounted(async () => {
            this.busService.addEventListener(
                "BUS:WORKER_STATE_UPDATED",
                this._onWorkerState,
            );
            for (const type of this._subscribedTypes) {
                this.busService.subscribe(type, this._onBusNotification);
            }
            await this.busService.addChannel("ai_debug");
        });

        onWillUnmount(() => {
            this.busService.removeEventListener(
                "BUS:WORKER_STATE_UPDATED",
                this._onWorkerState,
            );
            for (const type of this._subscribedTypes) {
                this.busService.unsubscribe(type, this._onBusNotification);
            }
            this.busService.deleteChannel("ai_debug");
        });
    }

    get statusColor() {
        return this.state.connectionStatus === "connected"
            ? "connected"
            : "disconnected";
    }

    get statusLabel() {
        switch (this.state.connectionStatus) {
            case "connected":
                return "Connected";
            case "reconnecting":
                return "Reconnecting...";
            case "disconnected":
                return "Disconnected";
            default:
                return "Connecting...";
        }
    }
}
