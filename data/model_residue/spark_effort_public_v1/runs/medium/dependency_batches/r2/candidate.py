from __future__ import annotations

from collections.abc import Iterable, Mapping


def dependency_batches(dependencies: Mapping[str, Iterable[str]]) -> list[list[str]]:
    if not dependencies:
        return []

    in_degree: dict[str, int] = {task: 0 for task in dependencies}
    dependents: dict[str, list[str]] = {task: [] for task in dependencies}
    prerequisites: dict[str, set[str]] = {task: set() for task in dependencies}

    for task, deps in dependencies.items():
        for dep in deps:
            if dep not in dependencies:
                raise ValueError(f"Unknown dependency: {dep}")
            if dep not in prerequisites[task]:
                prerequisites[task].add(dep)
                dependents[dep].append(task)
                in_degree[task] += 1

    ready = sorted(task for task, count in in_degree.items() if count == 0)
    processed: set[str] = set()
    batches: list[list[str]] = []

    while ready:
        batch = ready
        batches.append(batch)
        for task in batch:
            processed.add(task)
            for dependent in dependents[task]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    continue
        newly_ready = sorted(
            t for t, count in in_degree.items()
            if count == 0 and t not in processed and (len(batches[-1]) == 0 or t not in batch)
        )
        ready = []
        for t in newly_ready:
            if t not in processed and t not in ready:
                ready.append(t)

    if len(processed) != len(dependencies):
        raise ValueError("Dependency cycle detected")

    return [sorted(batch) for batch in batches]