"""Data pipeline — currently one giant function that does everything."""


def process_report(csv_text: str) -> str:
    """Parse CSV sales data, validate, compute stats, return formatted report.

    CSV format: name,region,amount,quarter
    Must handle: missing fields, negative amounts, duplicate entries.
    """
    lines = csv_text.strip().split("\n")
    if len(lines) < 2:
        return "ERROR: No data rows"

    header = [h.strip().lower() for h in lines[0].split(",")]
    if "name" not in header or "amount" not in header:
        return "ERROR: Missing required columns (need 'name' and 'amount')"

    name_idx = header.index("name")
    amount_idx = header.index("amount")
    region_idx = header.index("region") if "region" in header else None
    quarter_idx = header.index("quarter") if "quarter" in header else None

    records = []
    errors = []
    seen_keys = set()

    for i, line in enumerate(lines[1:], start=2):
        fields = [f.strip() for f in line.split(",")]
        if len(fields) < len(header):
            errors.append(f"Row {i}: too few fields")
            continue
        name = fields[name_idx]
        if not name:
            errors.append(f"Row {i}: empty name")
            continue
        try:
            amount = float(fields[amount_idx])
        except (ValueError, IndexError):
            errors.append(f"Row {i}: invalid amount")
            continue
        if amount < 0:
            errors.append(f"Row {i}: negative amount ({amount})")
            continue
        region = fields[region_idx] if region_idx is not None else "unknown"
        quarter = fields[quarter_idx] if quarter_idx is not None else "Q?"

        dedup_key = (name, region, quarter)
        if dedup_key in seen_keys:
            errors.append(f"Row {i}: duplicate entry for {name}/{region}/{quarter}")
            continue
        seen_keys.add(dedup_key)

        records.append({"name": name, "region": region, "quarter": quarter, "amount": amount})

    if not records:
        return "ERROR: No valid records\n" + "\n".join(errors)

    total = sum(r["amount"] for r in records)
    avg = total / len(records)
    max_rec = max(records, key=lambda r: r["amount"])
    min_rec = min(records, key=lambda r: r["amount"])

    by_region = {}
    for r in records:
        by_region.setdefault(r["region"], []).append(r["amount"])

    region_lines = []
    for reg in sorted(by_region):
        amounts = by_region[reg]
        region_lines.append(f"  {reg}: ${sum(amounts):,.2f} ({len(amounts)} sales)")

    report = []
    report.append(f"SALES REPORT")
    report.append(f"Records: {len(records)} valid, {len(errors)} errors")
    report.append(f"Total: ${total:,.2f}")
    report.append(f"Average: ${avg:,.2f}")
    report.append(f"Highest: {max_rec['name']} ${max_rec['amount']:,.2f}")
    report.append(f"Lowest: {min_rec['name']} ${min_rec['amount']:,.2f}")
    report.append(f"By Region:")
    report.extend(region_lines)
    if errors:
        report.append(f"Errors:")
        for e in errors:
            report.append(f"  {e}")

    return "\n".join(report)
