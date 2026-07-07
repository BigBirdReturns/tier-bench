"""
Optional model adapters. The harness core needs only a `call(prompt) -> str`;
these build one for common providers. Bring your own by writing the same shape —
it's two lines. The harness has no hard dependency on any of these.

    from capability_harness.backends import anthropic_backend
    call = anthropic_backend("claude-haiku-4-5")           # reads ANTHROPIC_API_KEY
    from capability_harness.uplift import review
    review(code, call)
"""
from __future__ import annotations

import os
from typing import Callable


def anthropic_backend(model: str, api_key: str | None = None,
                      max_tokens: int = 2000) -> Callable[[str], str]:
    """A `call` backed by the Anthropic SDK. `pip install anthropic`."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    def call(prompt: str) -> str:
        msg = client.messages.create(
            model=model, max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")

    return call


def openai_backend(model: str, api_key: str | None = None,
                   base_url: str | None = None, max_tokens: int = 2000) -> Callable[[str], str]:
    """A `call` backed by any OpenAI-compatible endpoint (OpenAI, Together, Groq,
    OpenRouter, vLLM, LM Studio, Ollama's OpenAI shim...). `pip install openai`.
    Pass `base_url` for non-OpenAI hosts."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"), base_url=base_url)

    def call(prompt: str) -> str:
        r = client.chat.completions.create(
            model=model, max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return r.choices[0].message.content or ""

    return call


def echo_backend() -> Callable[[str], str]:
    """A keyless no-op backend for wiring/smoke tests — returns a stub, calls no model."""
    def call(prompt: str) -> str:
        lens = prompt.split("LENS — ", 1)[-1].split(" only", 1)[0][:40]
        return f"[echo backend: no model called] would review through lens: {lens}"
    return call
