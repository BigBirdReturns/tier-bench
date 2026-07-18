from collections import defaultdict
import heapq
from typing import Mapping, Iterable, List


def dependency_batches(dependencies: Mapping[str, Iterable[str]]) -> List[List[str]]:
    if not dependencies:
        return []

    tasks = list(dependencies.keys())
    indegree = {task: 0 for task in tasks}
    dependents = {task: [] for task in tasks}

    for task, required in dependencies.items():
        seen = set()
        for dep in required:
            if dep not in indegree:
                raise ValueError(f"Unknown dependency: {dep}")
            if dep in seen:
                continue
            seen.add(dep)
            dependents[dep].append(task)
            indegree[task] += 1

    ready = [task for task, count in indegree.items() if count == 0]
    heapq.heapify(ready)

    batches: List[List[str]] = []
    processed = 0
    total = len(indegree)

    while ready:
        batch_size = len(ready)
        batch = []
        for _ in range(batch_size):
            task = heapq.heappop(ready)
            batch.append(task)
            processed += 1

            for dependent in dependents[task]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    heapq.heappush(ready, dependent)

        batches.append(batch)

    if processed != total:
        raise ValueError("Cycle detected in dependencies")

    return batches