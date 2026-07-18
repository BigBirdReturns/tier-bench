Return only one complete Python source file, with no Markdown fences or commentary.

Implement:

    def dependency_batches(dependencies):

`dependencies` maps each task name to an iterable of task names that must be completed first. Return deterministic execution batches as a list of lists. Every task in a batch must be ready before that batch begins; task names within each batch are lexicographically sorted. A dependency name that is not a key in the mapping is invalid. Raise `ValueError` for an unknown dependency or for any cycle, including a self-cycle. Return `[]` for an empty mapping. Do not mutate the input mapping or its dependency collections.

