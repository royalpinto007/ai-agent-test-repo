#!/usr/bin/env python3
"""Generate a battery of test CSVs from the real eBay payout for edge-case testing.

Run from this folder (Dolibarr-EBay/test-csvs/):
    python3 generate.py

Each output CSV is documented in README.md alongside it.
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path
from decimal import Decimal

HERE = Path(__file__).parent.resolve()
SOURCE = HERE.parent / "eBay Payout_7461554484_TXS - 4-21-26 (1).csv"

# ---------------------------------------------------------------------------
# Load the original CSV: preamble lines + header + data rows.

if not SOURCE.exists():
    print(f"Source CSV missing: {SOURCE}", file=sys.stderr)
    sys.exit(2)

with open(SOURCE, encoding="utf-8-sig") as f:
    raw_lines = f.read().splitlines()

header_idx = next(
    i for i, l in enumerate(raw_lines)
    if l.lstrip('"').startswith("Transaction creation date")
)
preamble = raw_lines[:header_idx]
header_line = raw_lines[header_idx]
data_lines = raw_lines[header_idx + 1:]

# Parse data rows into dicts (preserve original order).
reader = csv.DictReader([header_line] + data_lines)
header_cols = list(reader.fieldnames)
all_rows = list(reader)


def order_of(row: dict) -> str:
    return (row.get("Order number") or "").strip()


def net_of(row: dict) -> Decimal:
    s = (row.get("Net amount") or "").replace(",", "").strip()
    if not s or s == "--":
        return Decimal("0")
    try:
        return Decimal(s)
    except Exception:
        return Decimal("0")


# Group rows by order number (preserving order)
rows_by_order: dict[str, list[dict]] = {}
for r in all_rows:
    o = order_of(r)
    if not o or o == "--":
        continue
    rows_by_order.setdefault(o, []).append(r)

# Per-order totals
totals = {o: sum(net_of(r) for r in rs) for o, rs in rows_by_order.items()}

# ---------------------------------------------------------------------------
# Helpers


def write_csv(filename: str, rows: list[dict], *, payout_id: str | None = None,
              payout_date: str | None = None, payout_method: str | None = None,
              amount_line: str | None = None):
    """Emit a CSV at HERE/filename, with the same preamble + header as the source.
    Optionally rewrite payout-level fields on every row (so tests can simulate
    distinct payouts)."""
    out_path = HERE / filename
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        # Preamble: copy the original, optionally tweaking the Amount line.
        for line in preamble:
            if amount_line is not None and line.startswith('"Amount"'):
                f.write(amount_line + "\n")
            else:
                f.write(line + "\n")
        f.write(header_line + "\n")
        writer = csv.DictWriter(f, fieldnames=header_cols, quoting=csv.QUOTE_ALL)
        for r in rows:
            r2 = dict(r)
            if payout_id is not None:    r2["Payout ID"] = payout_id
            if payout_date is not None:  r2["Payout date"] = payout_date
            if payout_method is not None: r2["Payout method"] = payout_method
            writer.writerow(r2)
    return out_path


def rows_for_orders(orders: list[str]) -> list[dict]:
    out = []
    for o in orders:
        out.extend(rows_by_order.get(o, []))
    return out


def make_synthetic_order(order_number: str, *, rows: list[tuple[str, Decimal, str]],
                        payout_id: str = "9000000000",
                        payout_date: str = "May 26, 2026",
                        payout_method: str = "Test Bank - *0000",
                        tx_date: str = "May 25, 2026") -> list[dict]:
    """Build synthetic data rows for an order that doesn't exist in Dolibarr,
    so the reconciler should mark it MISSING_IN_DOLIBARR.

    rows: list of (Type, Net, Description) tuples.
    """
    out = []
    for i, (typ, net, desc) in enumerate(rows):
        r = {c: "" for c in header_cols}
        r["Transaction creation date"] = tx_date
        r["Type"]            = typ
        r["Order number"]    = order_number
        r["Legacy order ID"] = order_number
        r["Buyer username"]  = "testbuyer"
        r["Buyer name"]      = "Test Buyer"
        r["Net amount"]      = str(net)
        r["Payout currency"] = "USD"
        r["Payout date"]     = payout_date
        r["Payout ID"]       = payout_id
        r["Payout method"]   = payout_method
        r["Payout status"]   = "Funds sent"
        r["Reason for hold"] = "--"
        r["Transaction ID"]  = f"TEST-{order_number}-{i}"
        r["Item title"]      = desc
        r["Gross transaction amount"] = str(net)
        r["Transaction currency"]     = "USD"
        r["Description"]     = desc
        out.append(r)
    return out


# ---------------------------------------------------------------------------
# Selection logic — pick small representative groups by net signature.

# Bucket orders by sign and magnitude
positive_orders = sorted([o for o, t in totals.items() if t > 0], key=lambda o: totals[o])
negative_orders = sorted([o for o, t in totals.items() if t < 0], key=lambda o: totals[o], reverse=True)
zero_orders     = [o for o, t in totals.items() if t == 0]
multi_row_orders = sorted([o for o, rs in rows_by_order.items() if len(rs) >= 3],
                          key=lambda o: -len(rows_by_order[o]))
single_row_orders = [o for o, rs in rows_by_order.items() if len(rs) == 1]

# ---------------------------------------------------------------------------
# Generate CSVs

generated: list[tuple[str, str]] = []  # (filename, one-line description)


# 01: tiny — one positive single-row order. Smallest valid file.
o = next(o for o in positive_orders if len(rows_by_order[o]) == 1)
write_csv("01-tiny-positive.csv", rows_for_orders([o]),
          payout_id="TEST-0001-POS", payout_date="May 01, 2026",
          payout_method="Test Bank - *0001",
          amount_line=f'"Amount","{totals[o]} USD"')
generated.append(("01-tiny-positive.csv", f"1 order ({o}) positive net {totals[o]:.2f}, 1 CSV row"))

# 02: tiny negative — one negative single-row order.
neg_singles = [o for o in negative_orders if len(rows_by_order[o]) == 1]
o = neg_singles[0]
write_csv("02-tiny-negative.csv", rows_for_orders([o]),
          payout_id="TEST-0002-NEG", payout_date="May 02, 2026",
          payout_method="Test Bank - *0002",
          amount_line=f'"Amount","{totals[o]} USD"')
generated.append(("02-tiny-negative.csv", f"1 order ({o}) negative net {totals[o]:.2f}, 1 CSV row"))

# 03: multi-row — one order with the most CSV rows (tests grouping + breakdown)
o = multi_row_orders[0]
rows = rows_by_order[o]
write_csv("03-multi-row-order.csv", rows,
          payout_id="TEST-0003-MULTI", payout_date="May 03, 2026",
          payout_method="Test Bank - *0003",
          amount_line=f'"Amount","{totals[o]} USD"')
generated.append(("03-multi-row-order.csv", f"1 order ({o}) with {len(rows)} CSV rows summing to {totals[o]:.2f}"))

# 04: small mixed — 5 orders, mix of pos/neg
sel = [
    positive_orders[0],
    positive_orders[len(positive_orders)//2],
    negative_orders[0],
    negative_orders[-1],
    positive_orders[-1],
]
rows = rows_for_orders(sel)
amt = sum(totals[o] for o in sel)
write_csv("04-small-mixed.csv", rows,
          payout_id="TEST-0004-MIX", payout_date="May 04, 2026",
          payout_method="Test Bank - *0004",
          amount_line=f'"Amount","{amt} USD"')
generated.append(("04-small-mixed.csv", f"5 real orders, mixed signs, total {amt:.2f}"))

# 05: only positive orders — 10 of them
sel = positive_orders[-10:]
rows = rows_for_orders(sel)
amt = sum(totals[o] for o in sel)
write_csv("05-positive-only.csv", rows,
          payout_id="TEST-0005-POS10", payout_date="May 05, 2026",
          payout_method="Test Bank - *0005",
          amount_line=f'"Amount","{amt} USD"')
generated.append(("05-positive-only.csv", f"10 real positive-net orders, total {amt:.2f}"))

# 06: only negative orders — every order in the source that's negative
sel = negative_orders
rows = rows_for_orders(sel)
amt = sum(totals[o] for o in sel)
write_csv("06-negative-only.csv", rows,
          payout_id="TEST-0006-NEG", payout_date="May 06, 2026",
          payout_method="Test Bank - *0006",
          amount_line=f'"Amount","{amt} USD"')
generated.append(("06-negative-only.csv", f"{len(sel)} real negative-net orders, total {amt:.2f}"))

# 07: large amounts — 5 highest-magnitude orders
big = sorted(totals.items(), key=lambda kv: abs(kv[1]), reverse=True)[:5]
sel = [o for o, _ in big]
rows = rows_for_orders(sel)
amt = sum(totals[o] for o in sel)
write_csv("07-large-amounts.csv", rows,
          payout_id="TEST-0007-BIG", payout_date="May 07, 2026",
          payout_method="Test Bank - *0007",
          amount_line=f'"Amount","{amt} USD"')
generated.append(("07-large-amounts.csv", f"5 biggest-magnitude orders ($500+), total {amt:.2f}"))

# 08: all-synthetic — 5 fake orders that DON'T exist in Dolibarr.
synth_rows = []
synth_rows.extend(make_synthetic_order("99-FAKE-00001",
    rows=[("Order", Decimal("99.99"), "Synthetic - test missing")]))
synth_rows.extend(make_synthetic_order("99-FAKE-00002",
    rows=[("Order", Decimal("250.00"), "Synthetic - bigger missing"),
          ("Other fee", Decimal("-12.50"), "Promoted Listings fee")]))
synth_rows.extend(make_synthetic_order("99-FAKE-00003",
    rows=[("Refund", Decimal("-150.00"), "Synthetic - refund-only")]))
synth_rows.extend(make_synthetic_order("99-FAKE-00004",
    rows=[("Order", Decimal("0"), "Synthetic - zero net")]))
synth_rows.extend(make_synthetic_order("99-FAKE-00005",
    rows=[("Order", Decimal("75.50"), "Synthetic - last fake")]))
synth_amt = sum(net_of(r) for r in synth_rows)
write_csv("08-all-synthetic.csv", synth_rows,
          amount_line=f'"Amount","{synth_amt} USD"')
generated.append(("08-all-synthetic.csv", f"5 made-up order numbers (99-FAKE-...). Every row should be MISSING_IN_DOLIBARR"))

# 09: medium mixed — 25 orders sampled across the spectrum
sel_pool = positive_orders[:8] + positive_orders[-7:] + negative_orders[:5] + negative_orders[-5:]
sel = list(dict.fromkeys(sel_pool))  # de-dupe preserving order
rows = rows_for_orders(sel)
amt = sum(totals[o] for o in sel)
write_csv("09-medium-mixed.csv", rows,
          payout_id="TEST-0009-MED", payout_date="May 09, 2026",
          payout_method="Test Bank - *0009",
          amount_line=f'"Amount","{amt} USD"')
generated.append(("09-medium-mixed.csv", f"{len(sel)} real orders across the value spectrum, total {amt:.2f}"))

# 10: malformed rows — valid orders interleaved with garbage rows that should be skipped
mixed = rows_for_orders(positive_orders[:3])
# Add some malformed rows that the parser should silently skip:
garbage = []
g = {c: "" for c in header_cols}
g["Transaction creation date"] = "May 26, 2026"
g["Type"] = "Order"
g["Order number"] = "--"
g["Net amount"] = "10.00"
garbage.append(dict(g))      # missing order number
g["Order number"] = "99-GHOST-01"
g["Net amount"] = "--"
garbage.append(dict(g))      # missing net
g["Net amount"] = "not-a-number"
garbage.append(dict(g))      # bad net
out_rows = mixed[:1] + garbage[:1] + mixed[1:2] + garbage[1:2] + mixed[2:] + garbage[2:]
amt = sum(totals[o] for o in positive_orders[:3])
write_csv("10-malformed-rows.csv", out_rows,
          payout_id="TEST-0010-MAL", payout_date="May 10, 2026",
          payout_method="Test Bank - *0010",
          amount_line=f'"Amount","{amt} USD"')
generated.append(("10-malformed-rows.csv", f"3 good orders + 3 malformed rows (parser should silently skip the bad ones)"))

# 11: only-header (no data rows) — should fail gracefully or produce empty result
out_path = HERE / "11-empty.csv"
with open(out_path, "w", encoding="utf-8") as f:
    for line in preamble:
        f.write(line + "\n")
    f.write(header_line + "\n")
generated.append(("11-empty.csv", "Header row only, no data — tests empty-CSV handling"))

# 12: completely missing header — should error cleanly
out_path = HERE / "12-no-header.csv"
with open(out_path, "w", encoding="utf-8") as f:
    f.write('"This is not the header eBay produces"\n')
    f.write("some,random,data,rows\n")
    f.write("more,random,data,rows\n")
generated.append(("12-no-header.csv", "Bad CSV without the expected header — tests error handling"))

# ---------------------------------------------------------------------------
# Print summary

print("Generated test CSVs:")
for name, desc in generated:
    size = (HERE / name).stat().st_size
    print(f"  {name:30s}  {size:>6d} bytes  {desc}")
