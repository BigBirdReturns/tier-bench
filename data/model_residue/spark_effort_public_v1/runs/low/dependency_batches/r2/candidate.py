def dependency_batches(dependencies):
    """
    Return deterministic execution batches for a dependency graph.

    Args:
        dependencies: Mapping of task -> iterable of prerequisite task names.

    Returns:
        List of batches (each batch is a list of task names), where each batch is
        sorted lexicographically and all tasks are ready before the batch starts.

    Raises:
        ValueError: If a dependency refers to an unknown task, or if a cycle exists.
    """
    if not dependencies:
        return []

    task_names = set(dependencies.keys())
    graph = {}
    indegree = {}
    dependents = {task: set() for task in task_names}

    for task in task_names:
        prereqs = set(dependencies[task])
        if any(dep not in task_names for dep in prereqs):
            missing = sorted(dep for dep in prereqs if dep not in task_names)
            raise ValueError(f"Unknown dependency for {task}: {missing}")

        graph[task] = prereqs
        indegree[task] = len(prereqs)

    for task, prereqs in graph.items():
        for dep in prereqs:
            dependents[dep].add(task)

    ready = sorted(task for task, count in indegree.items() if count == 0)
    processed = set()
    batches = []

    while ready:
        current_batch = list(ready)
        batches.append(current_batch)

        next_ready = []
        for task in current_batch:
            processed.add(task)
            for dependent in dependents[task]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    next_ready.append(dependent)

        ready = sorted(next_ready)

    if len(processed) != len(task_names):
        raise ValueError("Dependency graph contains a cycle")

    return batches