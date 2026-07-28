# Estate Lab fixtures

`estate.example.json` is the human-owned map of project organs, adapters, routes, probes, authority requirements, fallback edges, and routing metrics. It is an executable estate model rather than an automatic discovery result. Repository discovery may report whether the mapped projects are present and healthy, but it may not invent or edit organ anatomy.

`scenarios/` contains the retained conformance and product experiments. Equivalence scenarios compare route-independent fingerprints from one action. Sequence scenarios exercise several controlled transitions over one state. Routing trials test route selection and refusal. Fault trials test explicit failure, idempotence, or fallback behavior.

A fixture change alters the experiment. Preserve the prior bytes in Git, state why the test changed, and do not compare new results to old results without acknowledging the changed manifest or scenario digest.
