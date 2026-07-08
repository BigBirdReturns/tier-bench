#!/usr/bin/env python3
"""Print the hidden-grader task set valid for breadth reproduction.

Only these tier-uplift tasks have hidden/objective graders suitable for an
agentic solver that must not see the answer key. Keep this list narrow: tasks
with visible answer keys or subjective graders are deliberately excluded.
"""

TASKS = [
    "experiments/tier-uplift/task01_parse_duration",
    "experiments/tier-uplift/task02_wildcard",
    "experiments/tier-uplift/task06_select",
]


def main() -> None:
    for task in TASKS:
        print(task)


if __name__ == "__main__":
    main()
