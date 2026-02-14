"""
LLM Cost Guard — Tier-based routing with hard spending limits.

Usage:
    from cost_guard import CostGuard, Tier

    guard = CostGuard(
        max_cost_per_call=0.50,       # refuse any single call over $0.50
        max_daily_spend=10.00,         # hard daily ceiling
        log_file="llm_costs.jsonl"     # audit trail
    )

    # Option A: Auto-route by tier (picks cheapest model at that tier)
    result = guard.call(
        tier=Tier.T2,
        messages=[{"role": "user", "content": "Fix the failing test in auth.py"}],
        provider="anthropic"  # or "openai"
    )

    # Option B: Explicit model (still enforces cost caps)
    result = guard.call(
        model="claude-haiku-4-5",
        messages=[{"role": "user", "content": "Sort these imports"}],
    )

    # Check spend
    guard.print_summary()

Supported providers:
    anthropic  — ANTHROPIC_API_KEY
    openai     — OPENAI_API_KEY
    deepseek   — DEEPSEEK_API_KEY (OpenAI-compatible)
    mistral    — MISTRAL_API_KEY
    google     — GEMINI_API_KEY
    ollama     — local, no key needed (start with: ollama serve)

Requirements:
    pip install anthropic openai mistralai google-genai --break-system-packages
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional


# ─── Tier definitions ───────────────────────────────────────────────

class Tier(Enum):
    T0 = 0   # Clerical: lint, format, rename
    T1 = 1   # Junior: implement from spec
    T2 = 2   # Mid: debug, integrate
    T3 = 3   # Senior: review, refactor
    T4 = 4   # Staff: plan, decompose
    T5 = 5   # Principal: architecture


# ─── Budget defaults per tier ────────────────────────────────────────

TIER_BUDGETS: dict[Tier, dict] = {
    Tier.T0: {"max_output_tokens": 500,  "max_tool_calls": 5},
    Tier.T1: {"max_output_tokens": 1000, "max_tool_calls": 8},
    Tier.T2: {"max_output_tokens": 1500, "max_tool_calls": 10},
    Tier.T3: {"max_output_tokens": 2000, "max_tool_calls": 15},
    Tier.T4: {"max_output_tokens": 3000, "max_tool_calls": 20},
    Tier.T5: {"max_output_tokens": 4000, "max_tool_calls": 30},
}


# ─── Model registry (loaded from models.json) ─────────────────────────
# Edit models.json to add models. Don't edit this file.

def _load_models_json() -> dict:
    """Load model registry from models.json next to this file."""
    config_path = Path(__file__).parent / "models.json"
    if not config_path.exists():
        raise FileNotFoundError(
            f"models.json not found at {config_path}. "
            "Copy models.json.example or create one — see README."
        )
    with open(config_path) as f:
        raw = json.load(f)
    return raw.get("models", {})


def _build_tables(models: dict) -> tuple[
    dict[str, tuple[float, float]],  # PRICING
    dict[str, str],                   # MODEL_PROVIDERS
    dict[Tier, list[str]],            # TIER_ROUTING
]:
    """Build pricing, provider, and routing tables from the model registry."""
    pricing = {}
    providers = {}
    # Collect models per tier ceiling
    tier_candidates: dict[Tier, list[tuple[float, str]]] = {t: [] for t in Tier}

    for name, info in models.items():
        inp = float(info.get("input_per_1M", 0))
        out = float(info.get("output_per_1M", 0))
        pricing[name] = (inp, out)
        providers[name] = info.get("provider", "unknown")

        ceiling_str = info.get("tier_ceiling", "T0")
        try:
            ceiling = Tier[ceiling_str]
        except KeyError:
            ceiling = Tier.T0

        # A model is a candidate for every tier at or below its ceiling
        total_cost = inp + out  # sort key: cheaper models first
        for t in Tier:
            if t.value <= ceiling.value:
                tier_candidates[t].append((total_cost, name))

    # Sort each tier's candidates by cost (cheapest first)
    routing = {}
    for t in Tier:
        candidates = tier_candidates[t]
        candidates.sort(key=lambda x: x[0])
        routing[t] = [name for _, name in candidates]

    return pricing, providers, routing


_MODELS_RAW = _load_models_json()
PRICING, _MODEL_PROVIDERS, TIER_ROUTING = _build_tables(_MODELS_RAW)


def _detect_provider(model: str) -> str:
    """Look up provider from the model registry."""
    return _MODEL_PROVIDERS.get(model, "unknown")


def _provider_available(provider: str) -> bool:
    """Check if a provider's API key is set (or if it's local)."""
    key_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "google": "GEMINI_API_KEY",
    }
    if provider == "ollama":
        # Check if Ollama is running locally
        try:
            import urllib.request
            urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1)
            return True
        except Exception:
            return False
    if provider == "openai-compat":
        # Check if we can reach the configured base_url for any openai-compat model
        for name, info in _MODELS_RAW.items():
            if info.get("provider") == "openai-compat":
                base_url = info.get("base_url", "http://localhost:8000")
                try:
                    import urllib.request
                    urllib.request.urlopen(f"{base_url.rstrip('/')}/models", timeout=1)
                    return True
                except Exception:
                    continue
        return False
    env_var = key_map.get(provider)
    return bool(os.environ.get(env_var)) if env_var else False


def available_providers() -> dict[str, bool]:
    """Return which providers are currently usable."""
    return {p: _provider_available(p) for p in
            ["anthropic", "openai", "deepseek", "mistral", "google", "ollama", "openai-compat"]}


# TIER_ROUTING is built from models.json above — no hardcoded routing table.


# ─── Cost estimation ─────────────────────────────────────────────────

def estimate_cost(model: str, input_tokens: int, max_output_tokens: int) -> float:
    """Estimate worst-case cost in USD."""
    if model not in PRICING:
        raise ValueError(f"Unknown model: {model}. Add it to PRICING table.")
    inp_rate, out_rate = PRICING[model]
    cost = (input_tokens / 1_000_000 * inp_rate) + (max_output_tokens / 1_000_000 * out_rate)
    return round(cost, 6)


def count_tokens_approx(messages: list[dict]) -> int:
    """Rough token count. 1 token ≈ 4 chars. Good enough for cost guard."""
    total_chars = sum(len(str(m.get("content", ""))) for m in messages)
    return max(total_chars // 4, 100)


# ─── Audit log ────────────────────────────────────────────────────────

@dataclass
class CallRecord:
    timestamp: str
    model: str
    tier: str
    input_tokens: int
    output_tokens: int
    estimated_cost: float
    actual_cost: float
    status: str  # "ok", "refused", "error", "escalated"
    reason: str = ""

    def to_dict(self) -> dict:
        return self.__dict__


# ─── Main guard ───────────────────────────────────────────────────────

@dataclass
class CostGuard:
    max_cost_per_call: float = 0.50
    max_daily_spend: float = 10.00
    log_file: str = "llm_costs.jsonl"
    daily_spend: float = field(default=0.0, init=False)
    call_count: int = field(default=0, init=False)
    records: list[CallRecord] = field(default_factory=list, init=False)
    _day: str = field(default="", init=False)

    def __post_init__(self):
        self._day = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _reset_if_new_day(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._day:
            self._day = today
            self.daily_spend = 0.0
            self.call_count = 0

    def _log(self, record: CallRecord):
        self.records.append(record)
        with open(self.log_file, "a") as f:
            f.write(json.dumps(record.to_dict()) + "\n")

    def _pick_model(self, tier: Tier, provider: Optional[str] = None) -> str:
        """Pick cheapest model for a tier, filtering by available providers."""
        candidates = list(TIER_ROUTING.get(tier, []))
        if provider:
            # Explicit provider filter
            candidates = [m for m in candidates if _detect_provider(m) == provider]
        else:
            # Auto-filter: only models whose provider is actually available
            candidates = [m for m in candidates if _provider_available(_detect_provider(m))]
        if not candidates:
            raise ValueError(f"No models available for {tier.name}" +
                             (f" with provider={provider}" if provider else
                              ". Set an API key or start Ollama."))
        return candidates[0]

    def call(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        tier: Optional[Tier] = None,
        provider: Optional[str] = None,
        system: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
        **kwargs,
    ) -> dict[str, Any]:
        """
        Make an LLM call with cost guard.

        Provide either `model` (explicit) or `tier` (auto-routes to cheapest).
        Returns dict with 'content', 'model', 'cost', 'usage', 'status'.
        """
        self._reset_if_new_day()

        # Resolve model
        if model is None and tier is None:
            raise ValueError("Provide either model= or tier=")
        if tier and model is None:
            model = self._pick_model(tier, provider)
        if tier is None:
            # Infer tier from model for budget defaults
            for t, models in TIER_ROUTING.items():
                if model in models:
                    tier = t
                    break
            if tier is None:
                tier = Tier.T2  # safe default

        # Resolve budgets
        budget = TIER_BUDGETS[tier]
        if max_output_tokens is None:
            max_output_tokens = budget["max_output_tokens"]

        # Estimate cost
        input_tokens = count_tokens_approx(messages)
        if system:
            input_tokens += len(system) // 4
        est_cost = estimate_cost(model, input_tokens, max_output_tokens)

        # ── GUARD: per-call limit ──
        if est_cost > self.max_cost_per_call:
            record = CallRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                model=model, tier=tier.name,
                input_tokens=input_tokens, output_tokens=0,
                estimated_cost=est_cost, actual_cost=0.0,
                status="refused",
                reason=f"Estimated ${est_cost:.4f} exceeds per-call limit ${self.max_cost_per_call:.2f}"
            )
            self._log(record)
            return {
                "content": None,
                "model": model,
                "cost": 0.0,
                "status": "refused",
                "reason": record.reason,
                "estimated_cost": est_cost,
            }

        # ── GUARD: daily limit ──
        if self.daily_spend + est_cost > self.max_daily_spend:
            record = CallRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                model=model, tier=tier.name,
                input_tokens=input_tokens, output_tokens=0,
                estimated_cost=est_cost, actual_cost=0.0,
                status="refused",
                reason=f"Daily spend ${self.daily_spend:.2f} + est ${est_cost:.4f} exceeds daily limit ${self.max_daily_spend:.2f}"
            )
            self._log(record)
            return {
                "content": None,
                "model": model,
                "cost": 0.0,
                "status": "refused",
                "reason": record.reason,
                "daily_spend_so_far": self.daily_spend,
            }

        # ── CALL ──
        detected_provider = _detect_provider(model)

        try:
            if detected_provider == "anthropic":
                result = self._call_anthropic(model, messages, system, max_output_tokens, **kwargs)
            elif detected_provider == "openai":
                result = self._call_openai(model, messages, system, max_output_tokens, **kwargs)
            elif detected_provider == "deepseek":
                result = self._call_deepseek(model, messages, system, max_output_tokens, **kwargs)
            elif detected_provider == "mistral":
                result = self._call_mistral(model, messages, system, max_output_tokens, **kwargs)
            elif detected_provider == "google":
                result = self._call_google(model, messages, system, max_output_tokens, **kwargs)
            elif detected_provider == "ollama":
                result = self._call_ollama(model, messages, system, max_output_tokens, **kwargs)
            elif detected_provider == "openai-compat":
                result = self._call_openai_compat(model, messages, system, max_output_tokens, **kwargs)
            else:
                raise ValueError(f"Provider '{detected_provider}' not implemented for model '{model}'.")

            # Calculate actual cost
            actual_in = result.get("usage", {}).get("input_tokens", input_tokens)
            actual_out = result.get("usage", {}).get("output_tokens", 0)
            actual_cost = estimate_cost(model, actual_in, actual_out)

            self.daily_spend += actual_cost
            self.call_count += 1

            record = CallRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                model=model, tier=tier.name,
                input_tokens=actual_in, output_tokens=actual_out,
                estimated_cost=est_cost, actual_cost=actual_cost,
                status="ok"
            )
            self._log(record)

            return {
                "content": result["content"],
                "model": model,
                "cost": actual_cost,
                "usage": result.get("usage", {}),
                "status": "ok",
            }

        except Exception as e:
            record = CallRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                model=model, tier=tier.name,
                input_tokens=input_tokens, output_tokens=0,
                estimated_cost=est_cost, actual_cost=0.0,
                status="error",
                reason=str(e)
            )
            self._log(record)
            return {
                "content": None,
                "model": model,
                "cost": 0.0,
                "status": "error",
                "reason": str(e),
            }

    def _call_anthropic(self, model, messages, system, max_output_tokens, **kwargs):
        import anthropic
        client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var
        api_kwargs = {
            "model": model,
            "max_tokens": max_output_tokens,
            "messages": messages,
        }
        if system:
            api_kwargs["system"] = system
        response = client.messages.create(**api_kwargs)
        return {
            "content": response.content[0].text if response.content else "",
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        }

    def _call_openai(self, model, messages, system, max_output_tokens, **kwargs):
        from openai import OpenAI
        client = OpenAI()  # uses OPENAI_API_KEY env var
        oai_messages = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        oai_messages.extend(messages)
        response = client.chat.completions.create(
            model=model,
            messages=oai_messages,
            max_tokens=max_output_tokens,
        )
        choice = response.choices[0]
        return {
            "content": choice.message.content or "",
            "usage": {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            }
        }

    def _call_deepseek(self, model, messages, system, max_output_tokens, **kwargs):
        """DeepSeek uses an OpenAI-compatible API."""
        from openai import OpenAI
        client = OpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
        )
        oai_messages = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        oai_messages.extend(messages)
        response = client.chat.completions.create(
            model=model,
            messages=oai_messages,
            max_tokens=max_output_tokens,
        )
        choice = response.choices[0]
        return {
            "content": choice.message.content or "",
            "usage": {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            }
        }

    def _call_mistral(self, model, messages, system, max_output_tokens, **kwargs):
        """Mistral API via the mistralai SDK."""
        from mistralai import Mistral
        client = Mistral(api_key=os.environ.get("MISTRAL_API_KEY"))
        mistral_messages = []
        if system:
            mistral_messages.append({"role": "system", "content": system})
        mistral_messages.extend(messages)
        response = client.chat.complete(
            model=model,
            messages=mistral_messages,
            max_tokens=max_output_tokens,
        )
        choice = response.choices[0]
        return {
            "content": choice.message.content or "",
            "usage": {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            }
        }

    def _call_google(self, model, messages, system, max_output_tokens, **kwargs):
        """Google Gemini via the google-genai SDK."""
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        # Build contents list
        contents = []
        for m in messages:
            role = "model" if m["role"] == "assistant" else "user"
            contents.append(types.Content(role=role, parts=[types.Part(text=m["content"])]))
        config = types.GenerateContentConfig(
            max_output_tokens=max_output_tokens,
        )
        if system:
            config.system_instruction = system
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )
        return {
            "content": response.text or "",
            "usage": {
                "input_tokens": response.usage_metadata.prompt_token_count if response.usage_metadata else 0,
                "output_tokens": response.usage_metadata.candidates_token_count if response.usage_metadata else 0,
            }
        }

    def _call_ollama(self, model, messages, system, max_output_tokens, **kwargs):
        """Local models via Ollama's OpenAI-compatible endpoint. Cost: $0."""
        from openai import OpenAI
        client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
        oai_messages = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        oai_messages.extend(messages)
        response = client.chat.completions.create(
            model=model,
            messages=oai_messages,
            max_tokens=max_output_tokens,
        )
        choice = response.choices[0]
        return {
            "content": choice.message.content or "",
            "usage": {
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            }
        }

    def _call_openai_compat(self, model, messages, system, max_output_tokens, **kwargs):
        """Any OpenAI-compatible endpoint (LMStudio, vLLM, text-gen-inference, etc.).
        Reads base_url and api_key_env from models.json."""
        from openai import OpenAI
        model_info = _MODELS_RAW.get(model, {})
        base_url = model_info.get("base_url", "http://localhost:8000/v1")
        api_key_env = model_info.get("api_key_env", "")
        api_key = os.environ.get(api_key_env, "none") if api_key_env else "none"
        client = OpenAI(base_url=base_url, api_key=api_key)
        oai_messages = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        oai_messages.extend(messages)
        response = client.chat.completions.create(
            model=model,
            messages=oai_messages,
            max_tokens=max_output_tokens,
        )
        choice = response.choices[0]
        return {
            "content": choice.message.content or "",
            "usage": {
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            }
        }

    # ── Escalation helper ──

    def escalate(
        self,
        messages: list[dict],
        current_tier: Tier,
        provider: Optional[str] = None,
        system: Optional[str] = None,
        max_escalations: int = 2,
        **kwargs,
    ) -> dict[str, Any]:
        """
        Try at current tier, escalate on failure up to max_escalations times.
        Returns the first successful result or the final failure.
        """
        tier = current_tier
        for attempt in range(max_escalations + 1):
            result = self.call(
                messages=messages,
                tier=tier,
                provider=provider,
                system=system,
                **kwargs,
            )
            if result["status"] == "ok":
                return result

            # Escalate
            next_val = tier.value + 1
            if next_val > Tier.T5.value:
                result["reason"] = (result.get("reason", "") +
                    " | Escalation exhausted. Needs human.")
                return result
            tier = Tier(next_val)

        result["reason"] = (result.get("reason", "") +
            f" | Max escalations ({max_escalations}) reached. Needs human.")
        return result

    # ── Reporting ──

    def print_summary(self):
        """Print cost summary to stdout."""
        print(f"\n{'='*50}")
        print(f"  LLM Cost Guard — Daily Summary")
        print(f"  Date: {self._day}")
        print(f"  Calls: {self.call_count}")
        print(f"  Spend: ${self.daily_spend:.4f} / ${self.max_daily_spend:.2f}")
        print(f"  Log: {self.log_file}")
        print(f"{'='*50}")
        if self.records:
            for r in self.records[-5:]:
                status_icon = {"ok": "✓", "refused": "✗", "error": "!"}
                icon = status_icon.get(r.status, "?")
                print(f"  {icon} {r.model:25s} {r.tier:4s} ${r.actual_cost:.4f}  {r.status}")
        print()


# ─── CLI usage ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("LLM Cost Guard — Interactive test")
    print("Checking for providers...")

    providers = available_providers()
    for name, avail in providers.items():
        icon = "✓" if avail else "✗"
        print(f"  {icon} {name}")

    if not any(providers.values()):
        print("\n⚠ No providers available.")
        print("  Set an API key or start Ollama (ollama serve).")
        print("  Running in dry-run mode (cost estimation only).\n")

    guard = CostGuard(
        max_cost_per_call=0.50,
        max_daily_spend=5.00,
    )

    # Demo: estimate costs for each tier
    print("Cost estimates by tier (worst case, max output tokens):\n")
    test_input = [{"role": "user", "content": "Fix the formatting in this file. " * 50}]
    for tier in Tier:
        # Show the cheapest model in each tier (regardless of availability)
        candidates = TIER_ROUTING.get(tier, [])
        if not candidates:
            continue
        model = candidates[0]
        budget = TIER_BUDGETS[tier]
        tokens_in = count_tokens_approx(test_input)
        est = estimate_cost(model, tokens_in, budget["max_output_tokens"])
        print(f"  {tier.name:4s} → {model:25s}  max_out={budget['max_output_tokens']:5d}  est=${est:.4f}")

    print(f"\n  Daily limit: ${guard.max_daily_spend:.2f}")
    print(f"  Per-call limit: ${guard.max_cost_per_call:.2f}")

    # Demo: show what happens when you exceed limits
    print("\n--- Simulating a refused call (per-call limit) ---")
    try:
        result = guard.call(
            tier=Tier.T5,
            messages=[{"role": "user", "content": "x " * 100000}],  # huge input
        )
        if result["status"] == "refused":
            print(f"  ✗ Refused: {result['reason']}")
            print(f"  Estimated cost was: ${result.get('estimated_cost', 0):.4f}")
        elif result["status"] == "error":
            print(f"  ! Error (expected without API key): {result.get('reason', '')[:80]}")
    except ValueError as e:
        print(f"  (skipped — no provider available for T5)")

    guard.print_summary()
