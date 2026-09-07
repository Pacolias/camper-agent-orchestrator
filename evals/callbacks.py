"""
LangChain callback handler for observability metrics (Metric 4).

Deliberately NOT wired into app/agents/supervisor.py's production signature —
see run_evals.py's module docstring for how this attaches to the graph
without any production code changes.
"""
from langchain_core.callbacks import BaseCallbackHandler


class TokenUsageTracker(BaseCallbackHandler):
    """Accumulates LLM call count and token usage across one graph invocation."""

    def __init__(self):
        self.llm_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def on_llm_end(self, response, **kwargs):
        self.llm_calls += 1
        for generation_list in response.generations:
            for generation in generation_list:
                message = getattr(generation, "message", None)
                usage = getattr(message, "usage_metadata", None) if message else None
                if usage:
                    self.input_tokens += usage.get("input_tokens", 0) or 0
                    self.output_tokens += usage.get("output_tokens", 0) or 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens
