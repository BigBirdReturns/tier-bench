from collections import defaultdict
from typing import Dict, Iterable, List


def dependency_batches(dependencies):
    """
    Return deterministic execution batches from a dependency mapping.

    Args:
        dependencies: Mapping of task -> iterable of prerequisite task names.

    Returns:
        List of batches, where each batch is a lexicographically sorted list of task names.

    Raises:
        ValueError: if a dependency references an unknown task or if a cycle exists.
    """
    if not dependencies:
        return []

    # Defensive copy of tasks to avoid depending on mapping mutation during processing.
    tasks = list(dependencies.keys())
    in_degree: Dict[str, int] = {task: 0 for task in tasks}
    dependents = defaultdict(list)

    # Build graph and compute indegrees, validating all dependencies exist.
    for task, prereqs in dependencies.items():
        try:
            prereq_set = set(prereqs)
        except TypeError as exc:
            # Non-iterable prerequisite collection
            raise TypeError(f"Dependencies for {task!r} must be an iterable") from exc

        for prereq in prereq_set:
            if prereq not in in_degree:
                raise ValueError(f"Unknown dependency {prereq!r} for task {task!r}")
            dependents[prereq].append(task)
            in_degree[task] += 1

    ready = {task for task, deg in in_degree.items() if deg == 0}
    batches: List[List[str]] = []
    processed = 0

    while ready:
        current_batch = sorted(ready)
        batches.append(current_batch)
        processed += len(current_batch)

        next_ready = set()
        for task in current_batch:
            for nxt in dependents.get(task, ()):
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    next_ready.add(nxt)

        ready = next_ready

    if processed != len(tasks):
        raise ValueError("Cycle detected in dependency graph")

    return batches