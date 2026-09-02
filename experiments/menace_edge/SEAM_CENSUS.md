# MENACE Edge Seam Census

Campaign: `menace-edge-01`  
Report: `menaceseamreport1_c14e3fc8ab0ca8bb4da52c2bf17693e6ad03be37db86706e638f56a8b6c52604`  
Minimal witness plan: `menaceseamplan1_c87ac8f53e8938b4c52f45b2fe9d58e06b473f27aa24319cb4e0beb09b4e9d79`

This report is a requirements-mining artifact. It inventories donor piles, repeated seams,
negative witnesses, and the smallest declared witness set that covers the mandatory seam
contract. It is not field acceptance and grants no production or action authority.

## Denominator

| Object | Count |
|---|---:|
| Donor piles | 6 |
| Sanitized donor records | 18 |
| Seams | 18 |
| Mandatory seams | 18 |
| Negative witnesses | 18 |
| Candidate integrated witnesses | 8 |
| Selected minimal witnesses | 5 |

## Minimal witness set

Declared cost: `31` units.  
Alternative optima: `0`.

- `witness.cooperative-handoff`
- `witness.multi-role-handoff`
- `witness.partitioned-controller`
- `witness.physical-availability`
- `witness.stack-recovery`

## Seam support

| Seam | Category | Piles | Witnesses | Minimum | State |
|---|---|---:|---:|---:|---|
| `seam.capture` | survival | 5 | 4 | 2 | multi_pile |
| `seam.custody` | survival | 5 | 5 | 2 | multi_pile |
| `seam.degradation` | survival | 5 | 3 | 2 | multi_pile |
| `seam.disposition` | judgment | 5 | 4 | 2 | multi_pile |
| `seam.execution` | survival | 3 | 1 | 1 | multi_pile |
| `seam.identity` | survival | 4 | 2 | 2 | multi_pile |
| `seam.interpretation` | judgment | 5 | 5 | 2 | multi_pile |
| `seam.outcome` | survival | 5 | 4 | 2 | multi_pile |
| `seam.reattachment` | judgment | 4 | 2 | 1 | multi_pile |
| `seam.reconciliation` | survival | 3 | 1 | 1 | multi_pile |
| `seam.resource-placement` | portability | 3 | 1 | 1 | multi_pile |
| `seam.role-aperture` | judgment | 4 | 2 | 1 | multi_pile |
| `seam.selection` | judgment | 4 | 3 | 2 | multi_pile |
| `seam.shift-handoff` | judgment | 3 | 1 | 1 | multi_pile |
| `seam.state-compilation` | survival | 6 | 4 | 2 | multi_pile |
| `seam.substitution` | portability | 3 | 1 | 1 | multi_pile |
| `seam.synchronization` | portability | 3 | 2 | 2 | multi_pile |
| `seam.track-handoff` | portability | 2 | 1 | 1 | multi_pile |

## Donor piles

| Pile | Donors | Witnesses | Seams | Evidence classes |
|---|---:|---:|---:|---|
| `pile.circulation-orchestration` | 3 | 3 | 13 | implemented_fixture |
| `pile.evidence-qualification` | 3 | 7 | 17 | implemented_fixture |
| `pile.local-control` | 3 | 2 | 11 | implemented_fixture, operator_observation, private_reported_trace |
| `pile.people-communications` | 3 | 4 | 16 | implemented_fixture, private_reported_trace |
| `pile.platform-sovereignty` | 3 | 1 | 6 | implemented_fixture, private_reported_trace |
| `pile.readiness-sustainment` | 3 | 2 | 9 | implemented_fixture, operator_observation |

## Highest-order pile intersections

| Piles | Shared seams | Shared integrated witnesses |
|---|---:|---:|
| `pile.circulation-orchestration` + `pile.evidence-qualification` + `pile.people-communications` | 11 | 2 |
| `pile.evidence-qualification` + `pile.local-control` + `pile.people-communications` | 10 | 1 |
| `pile.evidence-qualification` + `pile.people-communications` + `pile.readiness-sustainment` | 9 | 1 |
| `pile.circulation-orchestration` + `pile.evidence-qualification` + `pile.readiness-sustainment` | 8 | 1 |
| `pile.circulation-orchestration` + `pile.people-communications` + `pile.readiness-sustainment` | 8 | 1 |
| `pile.circulation-orchestration` + `pile.evidence-qualification` + `pile.local-control` | 6 | 0 |
| `pile.circulation-orchestration` + `pile.evidence-qualification` + `pile.platform-sovereignty` | 6 | 1 |
| `pile.circulation-orchestration` + `pile.local-control` + `pile.people-communications` | 6 | 0 |
| `pile.evidence-qualification` + `pile.local-control` + `pile.readiness-sustainment` | 6 | 0 |
| `pile.local-control` + `pile.people-communications` + `pile.readiness-sustainment` | 6 | 0 |
| `pile.circulation-orchestration` + `pile.local-control` + `pile.readiness-sustainment` | 5 | 0 |
| `pile.circulation-orchestration` + `pile.people-communications` + `pile.platform-sovereignty` | 4 | 0 |
| `pile.evidence-qualification` + `pile.people-communications` + `pile.platform-sovereignty` | 4 | 0 |
| `pile.circulation-orchestration` + `pile.local-control` + `pile.platform-sovereignty` | 2 | 0 |
| `pile.circulation-orchestration` + `pile.platform-sovereignty` + `pile.readiness-sustainment` | 2 | 0 |
| `pile.evidence-qualification` + `pile.local-control` + `pile.platform-sovereignty` | 2 | 0 |
| `pile.evidence-qualification` + `pile.platform-sovereignty` + `pile.readiness-sustainment` | 2 | 0 |
| `pile.local-control` + `pile.people-communications` + `pile.platform-sovereignty` | 2 | 0 |
| `pile.people-communications` + `pile.platform-sovereignty` + `pile.readiness-sustainment` | 2 | 0 |
| `pile.local-control` + `pile.platform-sovereignty` + `pile.readiness-sustainment` | 1 | 0 |

## Visible gaps

Uncovered mandatory seams: `0`.  
Under-supported mandatory seams: `0`.  
Seams supported by only one donor pile: `0`.

The control question is whether each selected witness can be replaced by an independent
implementation while preserving the same seam invariants, negative controls, and receipts.
