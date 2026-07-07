# Frozen generic review lenses

These five lenses are **task-independent** — a fixed decomposition of "review this
code," written with NO knowledge of any specific planted bug. They are frozen
here so the uplift experiments can be run *blind*: if a cheap model running this
generic sweep still reaches the tier above on an unseen task with untailored
bugs, the uplift is the harness's, not the experimenter's. (The task 03/04 sweeps
used bug-tailored lenses — a fair objection; this set removes that objection.)

Do not edit per task. If a lens must change, that is a new frozen version.

1. **Control flow & boundaries** — every loop bound, `range`, slice, index,
   early return, and termination condition. Trace a small example through any
   loop and count outputs against the intended count. Off-by-one, missed
   first/last element, wrong stop.

2. **State & effects** — mutation of arguments or shared/persistent state;
   aliasing; ordering of mutations vs checks; partial updates left un-rolled-back
   on an error path; two functions that disagree about an invariant.

3. **Data & types** — types and precision (int vs float, money as float),
   None/empty/degenerate inputs, conversions, comparisons that misbehave on ties
   or specific values.

4. **Contracts & errors** — missing input validation; silent failures; functions
   that return a misleading value instead of raising; unguarded division;
   documented invariants that the code can violate.

5. **Adversarial semantics** — assume the "obvious" implementation is subtly
   wrong and try to *break it*: is the whole approach (a greedy choice, a sort
   key, a recurrence) correct, or only correct on easy inputs? Actively construct
   a specific input that would expose a wrong algorithm, not just a wrong line.
