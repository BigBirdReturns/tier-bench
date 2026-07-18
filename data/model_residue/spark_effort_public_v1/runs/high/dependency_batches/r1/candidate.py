from __future__ import annotations

from typing import Mapping, Iterable, TypeVar

Task = TypeVar("Task")


def dependency_batches(dependencies: Mapping[Task, Iterable[Task]]) -> list[list[Task]]:
    """
    Return execution batches where each batch contains tasks whose dependencies are all
    satisfied before the batch starts. Tasks within each batch are lexicographically
    sorted. Raises ValueError on unknown dependencies or cycles (including self-cycles).
    """
    if not dependencies:
        return []

    indegree: dict[Task, int] = {}
    dependents: dict[Task, set[Task]] = {task: set() for task in dependencies}

    for task, prereqs in dependencies.items():
        prereq_set = set(prereqs)
        for prereq in prereq_set:
            if prereq not in dependencies:
                raise ValueError(f"Unknown dependency: {prereq!r}")
            dependents[prereq].add(task)
        indegree[task] = len(prereq_set)

    ready: list[Task] = sorted(task for task, count in indegree.items() if count == 0)
    remaining = set(dependencies.keys())
    batches: list[list[Task]] = []

    while ready:
        batch = ready
        batches.append(batch)
        ready = []

        for task in batch:
            remaining.remove(task)
            for follower in dependents[task]:
                indegree[follower] -= 1
                if indegree[follower] == 0:
                    ready.append(follower)

        ready.sort()

    if remaining:
        raise ValueError("Cyclic dependency detected")

    return batches