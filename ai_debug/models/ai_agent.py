from odoo import models


class AiAgent(models.Model):
    _inherit = 'ai.agent'

    def _ai_tool_request_sub_agent(self, tool_context, agent_id, prompt):
        """Override to thread parent linkage to subagent sessions.

        Injects both ai_parent_trace_id and ai_parent_tool_call_id into
        env.context so the child session's _run_agentic_loop can include
        them in its new_trace bus event.

        Both values come from tool_context (the mutable tools_context dict):
        - _debug_trace_id: set by _handle_tool_calls override (parent's trace UUID)
        - tool_call_id: set by the base _handle_tool_calls (LLM's call_id)

        We use tool_context rather than env.context because tool records
        (ir.actions.server) are fetched before _debug_ctx is set, so they
        never carry _debug_ctx in their env.
        """
        parent_trace_id = tool_context.get('_debug_trace_id')
        if parent_trace_id:
            self = self.with_context(
                ai_parent_trace_id=parent_trace_id,
                ai_parent_tool_call_id=tool_context.get('tool_call_id'),
            )
        return super()._ai_tool_request_sub_agent(tool_context, agent_id, prompt)
