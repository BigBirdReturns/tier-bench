"""Hidden semantic judge for t4_plan_decomposition — never shown to the solver.

The visible lint checks shape; this checks that the plan actually decomposes
REQUEST.md. Every assertion is derivable from the request text:
coverage (all three named files planned), scope (frozen output.py untouched),
dependency order (discount exists before report uses it), tier sanity, and
instruction specificity.
"""
import json
import sys
from pathlib import Path


def fail(msg: str) -> int:
    print(f"HIDDEN FAIL: {msg}")
    return 1


def main() -> int:
    plan = json.loads(Path("plan.json").read_text(encoding="utf-8"))
    by_file: dict[str, list[tuple[int, dict]]] = {}
    for i, sub in enumerate(plan):
        by_file.setdefault(sub["target_file"], []).append((i, sub))

    # 1. Coverage: each file named in the request gets at least one subtask.
    for required in ("pricing.py", "inventory.py", "report.py"):
        if required not in by_file:
            return fail(f"no subtask targets {required} (required by REQUEST.md)")

    # 2. Scope: the request explicitly freezes output.py.
    if "output.py" in by_file:
        return fail("a subtask targets output.py — REQUEST.md says do NOT touch it")
    for tf in by_file:
        if tf not in ("pricing.py", "inventory.py", "report.py"):
            return fail(f"subtask targets {tf}, which the request never asks to change")

    # 3. Dependency order: report.py uses pricing.discount, so the pricing
    #    subtask must come first (SUPERVISOR rule 3: order for dependencies).
    first_pricing = min(i for i, _ in by_file["pricing.py"])
    first_report = min(i for i, _ in by_file["report.py"])
    if first_pricing > first_report:
        return fail("report.py subtask ordered before pricing.py, but it depends on pricing.discount")

    # 4. Tier sanity: implement-from-spec is T1/T2; a behavioral bug fix is T2/T3.
    if not any(s["tier"] in ("T1", "T2") for _, s in by_file["pricing.py"]):
        return fail("pricing.py subtask mis-tiered: implementing discount() from a spec is T1/T2")
    if not any(s["tier"] in ("T2", "T3") for _, s in by_file["inventory.py"]):
        return fail("inventory.py subtask mis-tiered: fixing the <= bug is T2/T3, not clerical")

    # 5. Specificity: instructions must name the actual work (SUPERVISOR rule 4).
    def mentions(subs, *needles):
        return any(any(n in (s["instruction"] + " " + s["acceptance"]).lower() for n in needles)
                   for _, s in subs)

    if not mentions(by_file["pricing.py"], "discount"):
        return fail("pricing.py instruction never mentions the discount() function it must add")
    if not mentions(by_file["inventory.py"], "count_low_stock", "<="):
        return fail("inventory.py instruction names neither count_low_stock nor the <= fix")
    if not mentions(by_file["report.py"], "discount"):
        return fail("report.py instruction never mentions the discounted total it must add")

    print("HIDDEN OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
