from collections import defaultdict
from typing import Iterable, Mapping, Dict, List, Set


def dependency_batches(dependencies: Mapping[str, Iterable[str]]) -> List[List[str]]:
    """
    Group tasks into deterministic execution batches based on dependencies.

    Args:
        dependencies: Mapping from task name to an iterable of prerequisite task names.

    Returns:
        A list of batches, each batch is a lexicographically sorted list of tasks.

    Raises:
        ValueError: If a dependency is unknown (not a key in the mapping) or a cycle exists.
    """
    if not dependencies:
        return []

    task_names = set(dependencies.keys())

    indegree: Dict[str, int] = {task: 0 for task in task_names}
    dependents: Dict[str, Set[str]] = {task: set() for task in task_names}

    for task, prereqs in dependencies.items():
        seen_prereqs: Set[str] = set()
        for prereq in prereqs:
            if prereq not in task_names:
                raise ValueError(f"Unknown dependency: {prereq!r} for task {task!r}")
            if prereq == task:
                raise ValueError(f"Self dependency detected for task: {task!r}")
            if prereq in seen_prereqs:
                continue
            seen_prereqs.add(prereq)
            indegree[task] += 1
            dependents[prereq].add(task)

    ready = {task for task, count in indegree.items() if count == 0}
    batches: List[List[str]] = []
    processed = 0

    while ready:
        batch = sorted(ready)
        batches.append(batch)
        processed += len(batch)

        next_ready: Set[str] = set()
        for task in batch:
            for dependent in dependents.get(task, ()):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    next_ready.add(dependent)
        ready = next_ready

    if processed != len(task_names):
        raise ValueError("Cyclic dependency detected")

    return batches