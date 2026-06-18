"""Per-thread runtime state shared by ai_debug instrumentation.

A single ``ai_debug_tracker`` instance is written and read by both halves of
the instrumentation:

* ``ai_provider_patch._patched_request`` stashes the raw HTTP request body,
  the completion response, and the wall-clock LLM duration before/after each
  call, and ``pop_last_completion_data`` consumes those slots after every
  iteration.
* ``ai_session._run_agentic_loop`` stashes the dedicated debug env, the
  current loop/iteration ids, the originating uid, and an
  ``iteration_start_hook`` callback that lets the HTTP layer create a
  pending iteration row right before the (potentially long) LLM call
  begins.
* ``ir_actions_server._ai_tool_run`` stashes ``current_tool_call_db_id``
  while a tool is executing so nested loops can link their debug thread to
  the parent tool-call row.

``_AiDebugTracker`` subclasses ``threading.local``: Python invokes the
subclass ``__init__`` once per thread on first access, so every slot has a
defined default (``None``) and call sites can read them with plain
attribute access instead of ``getattr(..., default)``. Each OS thread still
has its own independent storage, so sub-agents running on separate threads
stay isolated from the parent loop.

Cleanup is per-side: ``pop_last_completion_data`` resets the completion
slots after every iteration, and ``_run_agentic_loop`` restores its own slots
at loop teardown. Neither side clears the other's state.
"""
import threading


class _AiDebugTracker(threading.local):
    """Thread-local slots used by both ai_provider_patch and ai_session."""

    def __init__(self):
        # ai_session._run_agentic_loop slots.
        self.debug_env = None
        self.loop_id = None
        self.iteration_id = None
        self.uid = None
        self.iteration_start_hook = None
        self.current_tool_call_db_id = None
        # ai_provider_patch._patched_request slots.
        self.last_completion_response = None
        self.last_llm_duration_ms = None
        self.last_request_body = None


ai_debug_tracker = _AiDebugTracker()
