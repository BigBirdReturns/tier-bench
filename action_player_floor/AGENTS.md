# Action Player Floor agent instructions

Read `START_HERE.md`, then `README.md`, `CONTINUITY.md`, and `COMMUNITY_MAP.md` before changing this directory or any Arc/World player-product surface.

The floor exists to prevent two recurring failures:

1. exact Arc law presented as a diagnostic fixture and mislabeled as the game;
2. a credible player-facing game that runs separate invented law.

Classify the object before editing. Ownership is derived from the touched plane:

```text
action timing, damage, objectives, cues, learning, outcomes  Arc
input, camera, animation, VFX, audio, HUD, engine            World
provider comparison                                          Tier Bench
trace and cue inspection                                     Tools
invalidator proposal                                         Hinge
human and physical evidence                                  Embodied
admitted job circulation                                     Bloodstream
product disposition                                          named authority
```

A cross-owner change must be split into explicit subtasks. Do not compensate later in the chain for an earlier defect. Presentation code may not mutate gameplay. Arc may not name a presentation provider. A provider may not enter the player intent. Source or conformance qualification may not be described as engine, human, or accepted evidence.

Before committing:

```bash
python -m unittest discover -s action_player_floor/tests -v
python action_player_floor/floor.py validate \
  --catalog action_player_floor/catalog.json \
  --intent action_player_floor/examples/underdrain.player-intent.json \
  --witnesses action_player_floor/examples/negative-witnesses.json \
  --changes action_player_floor/examples/change-proposals.json
python action_player_floor/floor.py report \
  --catalog action_player_floor/catalog.json \
  --intent action_player_floor/examples/underdrain.player-intent.json \
  --witnesses action_player_floor/examples/negative-witnesses.json \
  --changes action_player_floor/examples/change-proposals.json \
  --output /tmp/action-player-floor-report.json
cmp /tmp/action-player-floor-report.json action_player_floor/examples/floor-report.json
```

Do not add an aggregate readiness score. Do not remove a negative witness because the underlying failure is embarrassing. Do not claim a product pass while any lower evidence tier remains failed or open.
