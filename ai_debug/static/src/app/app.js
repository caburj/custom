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

        onMounted(async () => {
            this.busService.addEventListener(
                "BUS:WORKER_STATE_UPDATED",
                this._onWorkerState,
            );
            await this.busService.addChannel("ai_debug");
        });

        onWillUnmount(() => {
            this.busService.removeEventListener(
                "BUS:WORKER_STATE_UPDATED",
                this._onWorkerState,
            );
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
