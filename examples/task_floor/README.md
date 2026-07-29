# Task Floor examples

`reference_driver.py` is a dependency-free command driver used by the live TCK. It persists state and idempotency receipts under `TASK_FLOOR_DRIVER_ROOT`.

```bash
export TASK_FLOOR_DRIVER_ROOT=/tmp/task-floor-driver
python -m tier_runner.task_floor_cli driver-test \
  --command "python examples/task_floor/reference_driver.py"
```

`reference_action.json` and `reference_approval.json` are valid, content-addressed examples showing exact state and action binding.

`task_floor.rego` is an illustrative OPA admission policy. It admits preauthorized effects when state binding is valid and requires a matching approval for governed effects. The Python conformance host remains the reference implementation; the Rego file demonstrates the adapter input boundary.
