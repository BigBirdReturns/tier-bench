export const meta = {
  name: 'build-known-corner',
  description: 'Efficient firehose: fan cheap solvers over a hidden-graded corner in parallel, grade deterministically, escalate ONLY real walls, seal settled cells into an accumulating known-world corpus',
  phases: [
    { title: 'Floor', detail: 'cheap solver + deterministic hidden grader, parallel per task' },
    { title: 'Escalate', detail: 'stronger solver only on tasks the cheap floor failed' },
    { title: 'Seal', detail: 'append settled/liquid/open verdicts to the accumulating corpus (sediment)' },
  ],
}

const REPO = '/workspace/tier-bench'

// The "corner" = settled, hidden-graded tasks. Grow this list to grow the corner.
const CORNER = [
  { id: 'task01_parse_duration', kind: 'impl', symbol: 'parse_duration',
    dir: 'experiments/tier-uplift/task01_parse_duration', grader: 'hidden_tests.py' },
  { id: 'task02_wildcard', kind: 'impl', symbol: 'wildcard_match',
    dir: 'experiments/tier-uplift/task02_wildcard', grader: 'hidden_oracle.py' },
  { id: 'task06_select', kind: 'counterexample',
    dir: 'experiments/tier-uplift/task06_select', grader: 'grader.py' },
]

const CAND = { type: 'object', additionalProperties: false,
  properties: { candidate: { type: 'string' }, note: { type: 'string' } }, required: ['candidate'] }
const GRADE = { type: 'object', additionalProperties: false,
  properties: { passed: { type: 'boolean' }, score: { type: 'string' }, detail: { type: 'string' } },
  required: ['passed', 'detail'] }

function solvePrompt(t) {
  const base = `Work in ${REPO}. Read ONLY the public material for ${t.id}: `
    + `\`cat ${t.dir}/spec.md\` and \`cat ${t.dir}/visible_tests.py\` if it exists. `
    + `Do NOT open any hidden grader (${t.grader}, hidden_*, grader.py) — reading it voids the result.`
  if (t.kind === 'impl')
    return base + `\nReturn a complete self-contained Python implementation of \`${t.symbol}(...)\` `
      + `in the "candidate" field — code only, no prose, no markdown fences.`
  return base + `\nCounterexample task: return exactly one counterexample string in "candidate", `
    + `formatted precisely as: items=[...]; k=...`
}

function gradePrompt(t, candidate) {
  const run = t.kind === 'impl'
    ? `Write this candidate to /tmp/cand_${t.id}.py verbatim:\n\n${candidate}\n\nThen run: `
      + `python ${t.dir}/${t.grader} /tmp/cand_${t.id}.py`
    : `Run exactly: python ${t.dir}/${t.grader} --check ${JSON.stringify(candidate)}`
  const rule = t.kind === 'impl'
    ? `PASS iff the output shows "SCORE N/N" with both numbers EQUAL (all hidden cases pass).`
    : `PASS iff the output contains "COUNTEREXAMPLE: True".`
  return `Work in ${REPO}. You are the deterministic grader: you do NOT judge, you run the hidden `
    + `grader and report what it says.\n${run}\n${rule}\nReport passed(bool), the SCORE/verdict line `
    + `as "score", and the grader output tail as "detail". Report honestly even on failure/error.`
}

phase('Floor')
const floor = await pipeline(CORNER,
  (t) => agent(solvePrompt(t), { label: `solve:${t.id}`, phase: 'Floor', schema: CAND, model: 'haiku', effort: 'low' })
    .then(c => ({ t, candidate: c && c.candidate })),
  (prev, t) => {
    if (!prev || !prev.candidate) return { id: t.id, passed: false, detail: 'no candidate produced' }
    return agent(gradePrompt(t, prev.candidate), { label: `grade:${t.id}`, phase: 'Floor', schema: GRADE, model: 'haiku', effort: 'low' })
      .then(g => ({ id: t.id, passed: !!(g && g.passed), score: g && g.score, detail: (g && g.detail) || '' }))
  },
)

const walls = floor.filter(Boolean).filter(r => !r.passed)
log(`Floor: ${floor.filter(Boolean).filter(r => r.passed).length}/${CORNER.length} cleared cheap; ${walls.length} wall(s) to escalate`)

phase('Escalate')
const escalated = walls.length ? await parallel(walls.map(w => () => {
  const t = CORNER.find(c => c.id === w.id)
  return agent(solvePrompt(t) + `\n\nA cheaper model FAILED this (grader said: ${w.detail}). Reason from first principles and be rigorous.`,
    { label: `escalate-solve:${t.id}`, phase: 'Escalate', schema: CAND, effort: 'high' })
    .then(c => (c && c.candidate)
      ? agent(gradePrompt(t, c.candidate), { label: `escalate-grade:${t.id}`, phase: 'Escalate', schema: GRADE, model: 'haiku', effort: 'low' })
        .then(g => ({ id: t.id, passed: !!(g && g.passed), detail: (g && g.detail) || '' }))
      : { id: t.id, passed: false, detail: 'no candidate produced' })
})) : []

const esc = {}
for (const r of escalated.filter(Boolean)) esc[r.id] = r.passed
const corner = CORNER.map(t => {
  const f = floor.find(r => r && r.id === t.id)
  const clearedCheap = !!(f && f.passed)
  const clearedEsc = !!esc[t.id]
  const state = clearedCheap ? 'settled' : (clearedEsc ? 'liquid' : 'open')
  return { id: t.id, state, cleared_cheap: clearedCheap, needed_escalation: clearedEsc }
})

phase('Seal')
const sealReport = await agent(
  `Work in ${REPO}. This corpus ACCUMULATES like sediment — never rewrite prior lines.\n`
  + `1. Append ONE compact JSON line to experiments/breadth/run/known_corner.jsonl (create if absent) `
  + `with a "layer" note and this data: ${JSON.stringify({ corner })}.\n`
  + `2. Write/overwrite experiments/breadth/run/KNOWN_CORNER.md summarizing: how many cells are `
  + `settled (cleared by the cheap hidden-graded floor -> seal-and-forget, commoditized), liquid `
  + `(needed a stronger model -> keep a live model in the loop), and open (still a wall -> the frontier residue). `
  + `State explicitly that a re-run must DIFF against the newest layer and only re-probe non-'settled' cells, `
  + `so old sediment is never re-derived.\n`
  + `Do NOT git commit — only write the two files. Report exactly what you wrote.`,
  { label: 'seal', phase: 'Seal', model: 'haiku' })

return {
  corner,
  settled: corner.filter(c => c.state === 'settled').map(c => c.id),
  liquid: corner.filter(c => c.state === 'liquid').map(c => c.id),
  open: corner.filter(c => c.state === 'open').map(c => c.id),
  sealReport,
}