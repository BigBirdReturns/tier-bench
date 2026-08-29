# Historical rail surface — NOT CURRENT

Everything under this directory is **NOT CURRENT** and must not be executed,
copied, cited as the contract, or used as a starting point. It is retained only
so the lane's earlier claims stay auditable against the receipts that made them.

| Directory | What it was | Superseded by |
|---|---|---|
| `envelopes/` | v1 envelopes. The v1 controller accepted an envelope-supplied script path, digest and argv list. | `../envelopes-v3/` |
| `envelopes-v2/` | v2 envelopes. Closed schema, but no repository-operation manifest and no enforced resource ceilings. | `../envelopes-v3/` |
| `receipts/` | v1 and v2 receipts, their sidecars, and the v2 cold qualification. | `../receipts/` |

Receipt and envelope **bodies** in this tree named the deployment host, its
account home and absolute controller paths, so they are held in private holder
custody and each directory keeps an `EVIDENCE-INDEX.json` naming every retired
artifact by exact sha256. The evidence is retained; only its private
coordinates left the public tree.

## Why these are retired rather than deleted

The v1 envelope shape is the exact defect the layer law now forbids: issue text,
PR prose and model output must never become argv. A phase names an admitted
operation id and typed parameters, and the controller builds the command. The v1
fixtures are the evidence of what that mistake looked like, so they are kept
where they cannot be mistaken for a route.

## What is current

- controller — `../tbrail.py` (v4)
- envelopes — `../envelopes-v3/`
- receipts — `../receipts/` (v3 predecessor and v4)
- reproduction — `../run_proofs.sh`

The v3 receipts in `../receipts/` are **valid predecessor evidence**, not a
current contract: they were produced by the v3 controller at
`ad36bf604166b3f867f017470a3b68c872a7ab48`, whose settlement crash window,
checkpoint custody, profile anchor, receipt path handling and `preexec_fn`
launch path were all repaired in v4.
