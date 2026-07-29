# Start here: correcting AXM action-player drift

This is the cold-entry document for a new human or model. Do not begin by editing
Arc, World, a Unity scene, or a browser prototype.

## 1. Classify the object

State which object is wrong:

```text
action law
semantic cue
mechanic learning
input ingress
presentation mapping
engine integration
provider qualification
trace inspection
human evidence
job circulation
product acceptance
```

Run the ownership rule mentally or through `axm-action-player-change/1`:

| Touch | Owner |
|---|---|
| timing, damage, objective, outcome, cue meaning, learning, difficulty | Arc |
| input, camera, animation, VFX, audio, haptic, HUD, accessibility presentation, engine | World |
| provider comparison | Tier Bench |
| trace and cue inspection | Tools |
| invalidator proposal | Hinge |
| human or physical evidence | Embodied |
| admitted job circulation | Bloodstream |
| final disposition | named authority |

If a proposed patch touches more than one owner, split it into explicit subtasks. Do
not hide a cross-organ change inside one repository.

## 2. Locate the first divergence

Use this order:

```text
intent
→ exact Arc spec
→ admitted input
→ Arc state
→ Arc semantic cue
→ World cue consumption
→ animation / VFX / audio / camera / HUD response
→ provisional candidate
→ Arc replay
→ engine measurement
→ player observation
→ acceptance decision
```

Repair the first wrong cell. Do not compensate later in the chain. A mistimed
animation does not justify changing the parry window. A difficult parry does not
justify a local World multiplier. A poor camera does not justify changing actor
positions.

## 3. Compare against the negative witnesses

The floor requires three witnesses at minimum:

1. A Shine-quality renderer with local gameplay law.
2. Exact Arc law presented through a primitive diagnostic fixture and called a product.
3. A mandatory parry introduced only at the mastery encounter.

A repair that recreates any witness is drift, even when its tests are green.

## 4. Prepare the bounded change record

Copy a record from `examples/change-proposals.json`. Name:

- summary;
- touched planes;
- derived owner or coordinated subtasks;
- exact source references;
- rollback point;
- rollback proof;
- no aggregate score.

Run `floor.py validate`. The validator must agree with the owner.

## 5. Preserve the evidence ladder

Use exact language:

```text
source-qualified
conformance-qualified
engine-qualified
human-observed
accepted
```

Do not call source tests playable. Do not call a C# mirror Unity acceptance. Do not
call a scripted browser run an independent playtest. Do not call a provider benchmark
a product verdict.

## 6. Preserve the player boundary

A player build must:

- select exactly one production presentation adapter;
- refuse the primitive diagnostic adapter;
- map every required Arc cue;
- keep receipts and authority surfaces out of live play;
- retain remapping and accessibility profiles;
- teach a mandatory mechanic before testing it;
- retain an alternate when precision timing is not the core authored verb;
- emit only a provisional candidate;
- return through exact Arc replay.

## 7. Reconstruct the floor

```bash
python -m unittest discover -s action_player_floor/tests -v
python action_player_floor/floor.py validate \
  --catalog action_player_floor/catalog.json \
  --intent action_player_floor/examples/underdrain.player-intent.json \
  --witnesses action_player_floor/examples/negative-witnesses.json \
  --changes action_player_floor/examples/change-proposals.json
```

Then regenerate the report and require byte equality.

## 8. Hand off honestly

End the work with:

```text
what changed
which owner acted
which exact refs were used
which venues ran
which gates passed
which gates remain open
which negative witness was added or retired
what the rollback point is
what is explicitly not claimed
```

The control question is whether the next entrant can reproduce the same diagnosis
without trusting your memory, status language, screenshots, or confidence.
