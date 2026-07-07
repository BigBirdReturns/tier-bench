# Exact prompts — task07 taste pipeline

Verbatim prompts issued to each model (via Agent `model` override). Non-deterministic:
rerunning yields different text. Filenames match the committed snapshot.

## 1. Generate candidates (haiku, sonnet, opus — one each)
> Creative writing. Write the FIRST SENTENCE of a literary novel whose premise is: a woman discovers that her reflection has started acting a half-second late.
> Produce exactly 4 DISTINCT opening sentences — different in voice, image, and strategy. Each must be a single sentence, vivid and precise, the kind that makes a reader need the next line. No titles, no numbering commentary, no explanation.
> Write them to `gen/<tier>.txt`, ONE sentence per line, exactly 4 lines, nothing else.

## 2. Pool assembly (deterministic, no model)
12 candidates (4/tier) sorted by `sha256(text)` → IDs C01..C12. `pool_key.json` maps id→author tier (private). See the inline python in the session / `analyze.py` for the exact procedure.

## 3. Blind ranking (haiku, sonnet, opus — one each)
> You are judging opening sentences for a literary novel (premise: a woman discovers her reflection acts a half-second late). Below are 12 candidates, each with an ID. You do not know who wrote any of them. Judge purely on quality as an opening line — which most makes a reader need the next page: freshness of image, precision, voice, restraint, the pull into story.
> Read `pool.txt`. Rank ALL 12 from BEST to WORST. Output EXACTLY two lines to `judge/<tier>.txt`:
> `RANKING: <comma-separated IDs, best first, all 12>`
> `TOP: <best ID> — <one-line reason>`

## 4. Taste lens extraction (opus) — the "telling" transfer
> You are an expert literary editor. Articulate — as a reusable rubric — what makes a NOVEL OPENING SENTENCE genuinely excellent versus merely competent … 5-8 concrete, discriminating criteria … End with a one-line ordering principle. Write ONLY the rubric to `taste_lens.md`.

## 5. Rubric transfer (haiku ranks pool with the lens) → `judge/haiku_lens.txt`
> …judge strictly by the rubric in `taste_lens.md` — apply each criterion deliberately, do not use your own gut feel … rank ALL 12 … RANKING/TOP lines to `judge/haiku_lens.txt`.

## 6. Exemplar material (sonnet) — for the "showing" transfer
> Generate raw material … For EACH of three novel premises [A cartographer/map street; B faces forgotten; C birthday letter in own hand] write 6 DISTINCT opening sentences of deliberately VARIED quality … `exemplars/{A,B,C}.txt`, 6 lines each.

## 7. Demonstrations (opus ranks the 3 exemplar pools) → `exemplars/opus_rankings.md`
> …rank all 6 candidates from BEST to WORST … give a terse (≤12-word) reason so a learner could see WHY … `POOL X — RANKING: …` then each line with reason.

## 8. Exemplar transfer (haiku few-shot) → `judge/haiku_fewshot.txt`
> You are learning to rank … by studying a master editor's judgments, then applying that same taste to a new set. FIRST study `exemplars/opus_rankings.md` — absorb the PATTERN … THEN rank the new pool `pool.txt` the way that same editor would — apply the taste you just absorbed, not a checklist … RANKING/TOP to `judge/haiku_fewshot.txt`.

## Analysis (deterministic)
`analyze.py` (inter-judge ρ, consensus positions, self-preference), and the inline
ρ computation comparing `haiku.txt` / `haiku_lens.txt` / `haiku_fewshot.txt` against
the frontier rankings. `transfer.json` records the rubric-transfer result.
