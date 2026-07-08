# Subscription-surface prompt template

Use this template when pasting a public breadth task into a selected ChatGPT/Codex subscription model.

```text
You are the selected subscription-surface model: <exact UI/Codex model label>.

Task: <task_id>
Phase: <solo|harness>
Trial: <trial_number>

Use only the public task packet below. Do not assume access to hidden tests, hidden graders, answer keys, or repository files not shown here.

<PUBLIC_TASK_PACKET>

Output rule:
- For implementation tasks, return only the Python function implementation. No prose and no markdown.
- For counterexample tasks, return exactly one counterexample as: items=[...]; k=...
```

Generate concrete prompts with:

```bash
python experiments/breadth/subscription_run.py \
  --selected-model-label "<exact UI/Codex model label>" \
  --task-id all \
  --phase solo \
  --trial 1 \
  --prompt-dir /tmp/subscription-prompts
```

The generated prompts include only public task material: `spec.md`, intended public `subject.py` when present, and `visible_tests.py` when present. Hidden grader files and answer artifacts are not read into the prompt.
