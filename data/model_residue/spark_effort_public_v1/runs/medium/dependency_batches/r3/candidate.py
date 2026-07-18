from collections import defaultdict


def dependency_batches(dependencies):
    if not dependencies:
        return []

    # Copy dependency collections so input is never mutated.
    dependency_sets = {
        task: set(prereqs)
        for task, prereqs in dependencies.items()
    }

    dependents = defaultdict(set)
    indegree = {}

    for task, prereqs in dependency_sets.items():
        for prereq in prereqs:
            if prereq not in dependencies:
                raise ValueError(
                    f"Unknown dependency '{prereq}' for task '{task}'."
                )
            dependents[prereq].add(task)
        indegree[task] = len(prereqs)

    ready = sorted([task for task, count in indegree.items() if count == 0])
    batches = []

    while ready:
        batches.append(ready)
        next_ready = []
        for task in ready:
            for dependent in dependents[task]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    next_ready.append(dependent)
        ready = sorted(next_ready)

    if any(count > 0 for count in indegree.values()):
        raise ValueError("Dependency cycle detected.")

    return batches