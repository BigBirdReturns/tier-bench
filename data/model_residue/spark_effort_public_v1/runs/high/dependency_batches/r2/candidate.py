from collections.abc import Iterable, Mapping


def dependency_batches(dependencies: Mapping[str, Iterable[str]]) -> list[list[str]]:
    if not dependencies:
        return []

    tasks = set(dependencies.keys())
    indegree = {task: 0 for task in tasks}
    dependents: dict[str, set[str]] = {task: set() for task in tasks}

    for task, prereqs in dependencies.items():
        for prereq in set(prereqs):
            if prereq not in tasks:
                raise ValueError(f"Unknown dependency: {prereq}")
            dependents[prereq].add(task)
            indegree[task] += 1

    ready = sorted(task for task, count in indegree.items() if count == 0)
    batches: list[list[str]] = []
    processed = 0

    while ready:
        batch = list(ready)
        batches.append(batch)
        processed += len(batch)

        newly_ready: list[str] = []
        for task in batch:
            for dep in dependents[task]:
                indegree[dep] -= 1
                if indegree[dep] == 0:
                    newly_ready.append(dep)

        ready = sorted(newly_ready)

    if processed != len(tasks):
        raise ValueError("Cycle detected in dependencies")

    return batches