# Derived ledger rollup

Implement the two-stage ledger pipeline in this repository.

The input JSON has an integer `cutoff_period` and `records`. Each record has `id`, `account`, `period`, `kind`, `amount_cents`, `status`, and optional integer `priority`. Amounts are non-negative integers. Kinds are `invoice`, `credit`, `fee`, and `waiver`.

First, implement `src/ledger_stage.py`. It must read an input ledger and write a normalized JSON state to the output path. Preserve source order. Each normalized record must include `id`, `account`, `period`, `kind`, `amount_cents`, `status`, `priority`, `eligible`, `fee_relief_eligible`, and `source_index`. A record is eligible exactly when its status is `open` or `settled` and its period is less than or equal to the input cutoff. Fee relief is eligible exactly for a `waiver` with priority at least 2. The stage output must contain `schema: 1`, the cutoff, and the normalized records.

Second, implement `src/solution.py`. It must read only the normalized state path supplied on its command line and print one compact JSON object. For eligible records, group by account: invoices add to invoice cents, credits subtract from credit cents, fees add to fee cents, and eligible waivers add to relief cents. Adjusted fees are `max(0, fee_cents - relief_cents)`. Due is invoice plus credit plus adjusted fees. Include one sorted account object per account with the fields `account`, `invoice_cents`, `credit_cents`, `fee_cents`, `relief_cents`, `adjusted_fee_cents`, `due_cents`, and `record_count`, plus `grand_total_cents`.

The visible validator is `python run_visible.py`. Keep the two stages dependent: the final solution must fail when the normalized state file is absent. You may edit only `src/ledger_stage.py` and `src/solution.py`; generated normalized JSON is a runtime artifact. Do not edit the task, validator, or sample data.
