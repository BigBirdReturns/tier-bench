# HALO3 Cell Zero Observation Floor

The HALO3 Cell Zero proof floor freezes sixty-six cells before any model, host, peripheral, human interaction, or physical result is admitted. This observation floor is the next authority boundary. It converts one frozen plan cell into an exact activation packet, seals the execution candidate and independent hidden grade separately, admits either an accepted or refused observation, and compiles the resulting evidence without collapsing incompatible families into a leaderboard.

The floor does not call Fable, execute Kimi3, operate the 4060 or 3090 lanes, drive a personal node, bind a peripheral, observe a person, or accept a physical effect. It defines how those later transactions enter the campaign without allowing a model, process exit, dashboard, fixture, or operator narrative to certify itself.

## Transaction

```text
compiled 66-cell plan
        |
        | select one exact cell
        v
deterministic activation
        |
        | acceptance text remains hidden behind a digest
        v
controller-sealed candidate
        |
        | exact producer identity, inputs, outputs, metrics, outcomes, receipts
        v
independent hidden grade
        |
        | exact candidate hash, grader source, fixture hash, reasons, verdict
        v
accepted or refused observation
        |
        | no production or promotion claim
        v
branch-preserving observation ledger
```

The activation packet discloses the task identity, model identity mode, required fields, metrics, receipt identities, trial denominator, authority ceiling, and acceptance-contract digest. It does not disclose the hidden acceptance text. This prevents a model or provider treatment from optimizing against the grader after activation while preserving a deterministic proof that every treatment was judged against the intended contract.

The candidate packet is sealed by the controller around the actual execution product. The producer remains `candidate_only`. A Fable candidate must contain every provider-observational identity field frozen by the plan. A Kimi3 candidate must contain the exact open-weight revision, shard, configuration, tokenizer, runtime, quantization, hardware, and prompt-template evidence. The deterministic control must bind the exact controller, source, task, and validator bytes. Missing identity, malformed digests, insufficient trial count, missing metrics, missing receipts, production claims, self-acceptance fields, and nested score fields fail closed.

The grade is a separate object owned by `evidence-node`. It binds the exact candidate hash, hidden fixture hash, grader source hash, evaluated receipt identities, reasons, and accepted or refused verdict. An accepted fingerprint requires an accepted metric, zero consequential misses, and zero critical escaped defects. An accepted physical stage requires at least one independently observed physical outcome. Human bind, authority, decode, handoff, and custody receipts remain attributed to a human.

## No universal score

Fable, Kimi3, and the deterministic controller may clear different task families under different conditions and burdens. The ledger therefore reports exact cell coverage:

```text
measured
accepted
refused
unmeasured
fingerprint measured
physical-stage measured
```

It does not emit an overall score, aggregate score, winner, readiness number, or promotion decision. Family-level interpretation remains a later evidence projection over exact observations. The underlying candidate, grade, metrics, outcomes, and receipts remain embedded in each observation for clean replay.

## Commands

Generate the frozen plan first:

```console
python -m tier_runner.halo3_cell plan \
  --lab labs/halo3-cell-zero/lab.json \
  --fingerprint labs/halo3-cell-zero/model_fingerprint_contract.json \
  --out /tmp/halo3-plan.json
```

Activate one exact cell:

```console
python -m tier_runner.halo3_cell_observation activate \
  --plan /tmp/halo3-plan.json \
  --cell-id <exact-cell-id> \
  --out /tmp/activation.json
```

Seal a controller-assembled execution payload:

```console
python -m tier_runner.halo3_cell_observation seal-candidate \
  --activation /tmp/activation.json \
  --payload /tmp/candidate-payload.json \
  --out /tmp/candidate.json
```

Seal the independent hidden grade:

```console
python -m tier_runner.halo3_cell_observation seal-grade \
  --activation /tmp/activation.json \
  --candidate /tmp/candidate.json \
  --payload /tmp/grade-payload.json \
  --out /tmp/grade.json
```

Admit the accepted or refused observation:

```console
python -m tier_runner.halo3_cell_observation admit \
  --plan /tmp/halo3-plan.json \
  --activation /tmp/activation.json \
  --candidate /tmp/candidate.json \
  --grade /tmp/grade.json \
  --out /tmp/observation.json
```

Compile a campaign ledger from one or more observations:

```console
python -m tier_runner.halo3_cell_observation ledger \
  --plan /tmp/halo3-plan.json \
  --observation /tmp/observation.json \
  --out /tmp/ledger.json
```

## First live sequence

The first live transaction remains ordered:

1. Observe the actual estate and bind the exact host, GPU, runtime, model, and evidence-node identities.
2. Activate the deterministic-control cells and establish the no-model control.
3. Activate Fable with complete provider request, response, cost, latency, prompt, tool, and billing custody.
4. Activate Kimi3 only after exact model shards, configuration, tokenizer, runtime, quantization, prompt template, and hardware placement are bound.
5. Fill the fifty-four model cells without aggregate ranking.
6. Activate `stage-020-single-node` and require an independently observed harmless physical outcome before HALO3 enters.
7. Add the 4060 HALO3 node only against the matched cell-only baseline.
8. Continue through foreign bind, partition, HALO3 removal, head succession, passive synchronization, reconciliation, and replay.

## Claim boundary

Provider-free qualification proves deterministic activation, strict identity and metric custody, candidate and grade separation, physical-witness refusal, human-event attribution, exact observation replay, no-score ledger compilation, and cross-platform byte stability. It does not measure or accept a model, machine, network, peripheral, person, or physical result. No production, field, military, or promotion claim is authorized.
