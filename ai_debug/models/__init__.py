# Part of Odoo. See LICENSE file for full copyright and licensing details.

# agent_runtime_tracker exposes the shared `ai_debug_tracker` thread-local used
# by both ai_provider_patch and ai_session; import it first so both consumers
# see the same object.
from . import agent_runtime_tracker

# ai_provider_patch MUST be imported before any provider service is
# instantiated -- it monkey-patches AIApiService._request at module load time.
from . import ai_provider_patch

from . import ai_debug_thread
from . import ai_debug_loop
from . import ai_debug_iteration
from . import ai_debug_tool_call
from . import ai_session
from . import ir_actions_server
from . import ir_http
from . import res_users
