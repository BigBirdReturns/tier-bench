Fixes applied in this check
- Functional equivalence now compares baseline (pre-edit) vs post-edit execution snapshots.
- Prompts now include baseline run output and include other *.py files in fixture as read-only context.
- Canonical outputs stored per task_id under tasks/_canonical/<task_id>.py.
