from .anthropic_provider import AnthropicAdapter
from .base import ProviderConfig
from .deterministic_test import DeterministicTestAdapter
from .openai_compatible import OpenAICompatibleAdapter

ADAPTERS = {
    AnthropicAdapter.kind: AnthropicAdapter,
    OpenAICompatibleAdapter.kind: OpenAICompatibleAdapter,
    DeterministicTestAdapter.kind: DeterministicTestAdapter,
}


def build_adapter(cfg: ProviderConfig):
    cls = ADAPTERS.get(cfg.kind)
    if cls is None:
        raise ValueError(f"unknown AI provider kind {cfg.kind!r}; known: {sorted(ADAPTERS)}")
    return cls(cfg)
