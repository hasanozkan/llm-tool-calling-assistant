"""Build the router from the environment. The default — the scripted model —
needs no key, so `make run` and CI work out of the box.

  ASSISTANT_PROVIDER=scripted | anthropic | openai
  ASSISTANT_MODEL=<model id>            (anthropic / openai)
  ASSISTANT_STRONG_MODEL=<model id>     optional: the escalation tier
  ANTHROPIC_API_KEY / OPENAI_API_KEY, OPENAI_BASE_URL (any OpenAI-compatible endpoint)
"""

import os

from assistant.llm.anthropic import Anthropic
from assistant.llm.gateway import LLMProvider, Router
from assistant.llm.openai_compat import OpenAICompatible
from assistant.llm.scripted import ScriptedModel


def _provider(kind: str, model: str) -> LLMProvider:
    if kind == "anthropic":
        return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], model=model)
    if kind == "openai":
        return OpenAICompatible(
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            api_key=os.environ["OPENAI_API_KEY"],
            model=model,
        )
    raise ValueError(f"unknown provider {kind!r}")


def router_from_env(mistakes: frozenset[str] = frozenset()) -> Router:
    kind = os.environ.get("ASSISTANT_PROVIDER", "scripted")
    if kind == "scripted":
        return Router({"fast": [ScriptedModel(mistakes=mistakes)]})
    fast = _provider(kind, os.environ["ASSISTANT_MODEL"])
    strong_id = os.environ.get("ASSISTANT_STRONG_MODEL")
    return Router({"fast": [fast], "strong": [_provider(kind, strong_id)] if strong_id else [fast]})
