# ChatGPT UI subscription capture template

1. Generate a public prompt packet with `subscription_run.py`.
2. Select exactly: `{model_family} / {intelligence}` in the ChatGPT UI.
3. Paste only the public `prompt_text` into a fresh chat. Never paste hidden grader content.
4. Copy the exact raw model answer into `raw_output`.
5. Preserve selector metadata and optional visible thought seconds/screenshot hash.

Expected answer formats:
- `task01_parse_duration` / `task02_wildcard`: a single Python function only; no prose or markdown fences.
- `task06_select`: exactly `items=[...]; k=...`.
