from odoo import models


class AiAgent(models.Model):
    _inherit = 'ai.agent'

    def _ai_tool_request_sub_agent(self, tool_context, agent_id, prompt):
        """Override to thread parent tool_call_id to subagent sessions.

        The base _handle_tool_calls sets tools_context['tool_call_id'] to the LLM's
        call_id for the current tool. When a subagent tool is invoked, this ID
        identifies which parent tool call spawned the subagent. We inject it into
        env.context so the child session's _run_agentic_loop can include it in
        its new_trace bus event as parent_tool_call_id.

        Only injects when _debug_ctx is present (instrumentation active).
        """
        if self.env.context.get('_debug_ctx'):
            self = self.with_context(
                ai_parent_tool_call_id=tool_context.get('tool_call_id'),
            )
        return super()._ai_tool_request_sub_agent(tool_context, agent_id, prompt)
