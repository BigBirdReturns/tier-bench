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

Copy the example files to `.local.json` names before changing paths, credentials, aliases, or source selections. Local files should not be committed when they contain credentials or operator-only paths.

External scores do not settle the local floor. They provide a comparison distribution, identify missing models and task families, and open reproduction work. Internal task receipts remain the authority for local routing.
