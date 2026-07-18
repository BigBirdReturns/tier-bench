from collections import defaultdict


def dependency_batches(dependencies):
    """
    Determine deterministic execution batches from a dependency mapping.

    Parameters
    ----------
    dependencies : Mapping[str, Iterable[str]]
        Maps task -> tasks that must be completed before it.

    Returns
    -------
    List[List[str]]
        List of batches, each batch sorted lexicographically.

    Raises
    ------
    ValueError
        If a dependency references an unknown task or if a cycle exists.
    """
    if not dependencies:
        return []

    tasks = set(dependencies.keys())
    remaining_in_degree = {}
    dependents = defaultdict(set)

    for task, required in dependencies.items():
        required_set = set(required)

        for dep in required_set:
            if dep not in tasks:
                raise ValueError(f"Unknown dependency: {dep}")

        remaining_in_degree[task] = len(required_set)
        for dep in required_set:
            dependents[dep].add(task)

    ready = sorted(task for task, count in remaining_in_degree.items() if count == 0)
    processed = set()
    batches = []

    while ready:
        batch = ready
        batches.append(batch)
        ready_candidates = []

        for task in batch:
            processed.add(task)
            for dependent in dependents.get(task, ()):
                remaining_in_degree[dependent] -= 1
                if remaining_in_degree[dependent] == 0:
                    ready_candidates.append(dependent)

        ready = sorted(ready_candidates)

    if len(processed) != len(tasks):
        raise ValueError("Dependency cycle detected")

    return batches