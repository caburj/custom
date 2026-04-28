/** @odoo-module **/
import { AiDebugApp } from "@ai_debug/app/app";
import { patch } from "@web/core/utils/patch";
import { useState, onMounted, onWillUnmount, onPatched, useRef } from "@odoo/owl";

patch(AiDebugApp.prototype, {
    setup() {
        super.setup();

        this.mcpCalls = useState([]);
        this._mcpState = useState({ tabActive: false, checkedMcpCallIds: new Set() });
        this.mcpSelectAllRef = useRef("mcpSelectAll");

        this._onMcpToolCall = (payload) => {
            this.mcpCalls.unshift({
                call_id: payload.call_id,
                tool_name: payload.tool_name,
                args: payload.args || {},
                result: payload.result,
                error: payload.error || null,
                success: payload.success,
                duration_ms: payload.duration_ms || 0,
                triggered_confirmation: false,
                confirmation_message: null,
                status: "completed",
            });
        };

        onMounted(async () => {
            this.busService.subscribe("mcp_tool_call", this._onMcpToolCall);
        });

        onWillUnmount(() => {
            this.busService.unsubscribe("mcp_tool_call", this._onMcpToolCall);
        });

        onPatched(() => {
            if (this.mcpSelectAllRef.el) {
                this.mcpSelectAllRef.el.indeterminate = this.someMcpChecked;
            }
        });
    },

    get mcpTabActive() {
        return this._mcpState.tabActive;
    },

    setMcpTab(active) {
        this._mcpState.tabActive = active;
        this._mcpState.checkedMcpCallIds.clear();
    },

    get allMcpChecked() {
        return this.mcpCalls.length > 0 && this._mcpState.checkedMcpCallIds.size === this.mcpCalls.length;
    },

    get someMcpChecked() {
        return this._mcpState.checkedMcpCallIds.size > 0 && !this.allMcpChecked;
    },

    toggleMcpCallCheck(callId) {
        if (this._mcpState.checkedMcpCallIds.has(callId)) {
            this._mcpState.checkedMcpCallIds.delete(callId);
        } else {
            this._mcpState.checkedMcpCallIds.add(callId);
        }
    },

    toggleSelectAllMcp() {
        if (this.allMcpChecked) {
            this._mcpState.checkedMcpCallIds.clear();
        } else {
            for (const call of this.mcpCalls) {
                this._mcpState.checkedMcpCallIds.add(call.call_id);
            }
        }
    },

    deleteCheckedMcpCalls() {
        const ids = new Set(this._mcpState.checkedMcpCallIds);
        this._mcpState.checkedMcpCallIds.clear();
        if (ids.has(this.state.selectedId)) {
            this.state.selectedId = null;
            this.state.selectedType = null;
        }
        for (let i = this.mcpCalls.length - 1; i >= 0; i--) {
            if (ids.has(this.mcpCalls[i].call_id)) {
                this.mcpCalls.splice(i, 1);
            }
        }
    },

    getSelectedMcpCall() {
        return this.mcpCalls.find((c) => c.call_id === this.state.selectedId) || null;
    },
});
