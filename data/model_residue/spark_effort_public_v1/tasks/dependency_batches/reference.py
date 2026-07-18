def dependency_batches(dependencies):
    graph = {name: set(required) for name, required in dependencies.items()}
    names = set(graph)
    if any(required - names for required in graph.values()):
        raise ValueError("unknown dependency")
    remaining = set(names)
    done = set()
    batches = []
    while remaining:
        ready = sorted(name for name in remaining if graph[name] <= done)
        if not ready:
            raise ValueError("cycle")
        batches.append(ready)
        done.update(ready)
        remaining.difference_update(ready)
    return batches

