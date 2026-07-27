# Universal Model Floor Experiment

This directory holds the operator-editable contracts for a full model floor.

```text
models.json
  -> tierfloor registry-from-models
  -> runtime-attested model and surface registry

model-waterline reports
  -> tierfloor ingest-waterline
  -> internal accepted-outcome observations

sources.example.json
  -> tierfloor sync
  -> external benchmark observations and community claim records

floor.example.json
  -> tierfloor compute
  -> one floor per task family plus a full measured/unmeasured model matrix
```

The default external source estate includes the Hugging Face official benchmark catalog, SWE-bench Verified, Humanity's Last Exam, and current LM Arena text, agent, web-development, search, and document cells. GitHub and approved Reddit sources collect practitioner findings around Aider, LiveBench, Terminal-Bench, OSWorld, function calling, local runtime behavior, cost, memory, and failures. Generic JSON, CSV, Atom, Hugging Face model-eval, and manual JSONL adapters remain available for additional communities and leaderboards.

Copy the example files to `.local.json` names before changing paths, credentials, aliases, or source selections. Local files should not be committed when they contain credentials or operator-only paths.

External scores do not settle the local floor. They provide a comparison distribution, identify missing models and task families, and open reproduction work. Internal task receipts remain the authority for local routing. Each benchmark revision, scaffold, tool policy, retry count, context policy, metric, and direction remains a separate comparison cell.
