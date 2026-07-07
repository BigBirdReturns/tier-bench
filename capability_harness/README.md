# capability_harness

**Lift a cheap model to the tier above — on operational tasks — with your own model, any provider.**

A single review pass misses what it doesn't look for. This runs a fixed set of
five **generic, task-independent lenses** — one focused pass each — and unions the
findings. *"Iteration can only buy what selection can see"*; the lens is what makes
it see. That's the whole mechanism.

It is deliberately small: **zero required dependencies**, **model-agnostic** (you
pass a `call(prompt) -> str` for whatever model you run), and the lenses are
**frozen** (not tuned to your code).

## Why it exists (the evidence)

Measured in [`experiments/tier-uplift`](../experiments/tier-uplift/LEDGER.md),
real model instances, blind:

- **haiku + this sweep = sonnet** on subtle bug-finding it missed solo (6/7 → 7/7).
- **haiku + the frozen generic sweep BEAT opus-solo** on an unseen task (5/5 vs 4/5) — the lenses were written before the bugs, so the lift is the harness's, not tailoring.
- On a task where the cheap model genuinely *couldn't derive* the answer, letting it **search** (write a checker, differentially test) beat opus **~4.7× cheaper**.

The frontier's operational edge is largely an *allocation* advantage — it looks in
more places per pass. This externalizes that allocation into a checklist any model
can run. What it does **not** touch is "sand": surface-form variance among
operationally-equivalent outputs (which of two good phrasings; taste on near-ties).
That carries no operational knowledge — see the ledger's correction note.

## Use it

```python
from capability_harness import review
from capability_harness.backends import anthropic_backend   # or openai_backend

call = anthropic_backend("claude-haiku-4-5")                # reads ANTHROPIC_API_KEY
result = review(open("mycode.py").read(), call)
print(result.merged_text())
```

Bring your own model — the core needs only a `call(prompt) -> str`:

```python
def call(prompt: str) -> str:
    return my_llm.generate(prompt)          # any provider, any SDK, local or remote
review(code, call)
```

CLI:

```bash
python -m capability_harness review mycode.py --model claude-haiku-4-5
python -m capability_harness review mycode.py --backend openai --model gpt-4.1-mini
python -m capability_harness review mycode.py --backend openai \
    --model llama3.1 --base-url http://localhost:11434/v1     # local Ollama
python -m capability_harness review mycode.py --backend echo  # no key, smoke test
```

## Honest limits

- **Operational tasks, not sand.** It lifts coverage/correctness/judgment (things
  with a right-ish answer). It will not make a cheap model's *prose taste* match a
  frontier model's — but that difference is mostly operationally inert anyway.
- **Recall up, tokens up.** Five passes cost ~5× a single review. You're buying
  recall (and, for cheap models, doing it for far less than one frontier pass).
- **The frontier still mints the frames.** These lenses were distilled from strong
  models. The harness *amortizes* the frontier — capture the move once, run it cheap
  forever — it doesn't eliminate it. That's the trade: renting per query → owning a
  reusable checklist.

## Extend — and grow the library

`DEFAULT_LENSES` is a plain list of `Lens(key, instruction)`. Add your own, or pass
a custom set to `review(target, call, lenses=...)`. Keep them **generic** — the
proof of portability is that the same set works on code it has never seen.

The library is meant to **compound**. Every validated community lens lives in
[`lenses_contrib.py`](lenses_contrib.py); `all_lenses()` unions them with the frozen
five (defaults keep priority):

```python
from capability_harness import review
from capability_harness.lenses_contrib import all_lenses
review(code, call, lenses=all_lenses())
```

A lens earns its place by one objective bar: on a **held-out** subject, its pass
surfaces a real issue the model's plain pass missed. Prove it with
[`scripts/validate_lens.py`](../scripts/validate_lens.py), add a `ContribLens` entry
with provenance, open a PR. Full guide: repo [`CONTRIBUTING.md`](../CONTRIBUTING.md)
→ *Contribute a lens*.
