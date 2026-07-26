# World Experience Atlas

This directory records mature engineering patterns that the sovereign desktop
estate has not yet fully operationalized.

Each entry in `atlas.json` names:

- the source discipline and mechanism;
- the current estate gap;
- a desktop translation;
- a falsifiable first experiment;
- dependencies and failure default;
- expected attention return, reuse radius, implementation cost, and risk.

The atlas is a planning surface, not implementation evidence.

```console
tieratlas validate --atlas experiments/world_experience/atlas.json
tieratlas catalog --atlas experiments/world_experience/atlas.json
tieratlas plan --atlas experiments/world_experience/atlas.json --limit 12
```

See `docs/world-experience-atlas.md` for the operating argument.
