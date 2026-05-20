#!/usr/bin/env python3
"""eBay payout vs Dolibarr reconciliation.

Groups an eBay payout CSV by Order number, sums the Net amount, then for each
order looks up the Sales Order in Dolibarr by ref_client, walks every linked
invoice and credit note, sums their net (total_ht), and reports per-order
discrepancies.

Usage:
    python reconcile.py <payout.csv> [--url URL] [--key API_KEY] [--tolerance 0.01]

Env vars (used if flags omitted):
    DOLIBARR_URL, DOLIBARR_API_KEY
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Iterable

import requests

EBAY_HEADER_KEY = "Transaction creation date"  # first column of the real header row
ORDER_COL = "Order number"
NET_COL = "Net amount"


def load_ebay_groups_from_text(text: str) -> dict[str, dict]:
    """Parse a payout CSV given as a single string. Returns
    {order_number: {"net": Decimal, "rows": int, "types": set[str]}}."""
    lines = text.splitlines()
    header_idx = -1
    for i, line in enumerate(lines):
        # Trim a possible UTF-8 BOM on the very first line.
        candidate = line.lstrip("﻿").lstrip('"').strip()
        if candidate.startswith(EBAY_HEADER_KEY):
            header_idx = i
            break
    if header_idx == -1:
        raise RuntimeError(f"Could not find header row starting with {EBAY_HEADER_KEY!r}")

    reader = csv.DictReader(lines[header_idx:])
    groups: dict[str, dict] = defaultdict(lambda: {"net": Decimal("0"), "rows": 0, "types": set()})
    for row in reader:
        order = (row.get(ORDER_COL) or "").strip()
        if not order or order in ("--", ""):
            continue
        net_raw = (row.get(NET_COL) or "").replace(",", "").strip()
        if not net_raw or net_raw == "--":
            continue
        try:
            net = Decimal(net_raw)
        except InvalidOperation:
            continue
        g = groups[order]
        g["net"] += net
        g["rows"] += 1
        g["types"].add((row.get("Type") or "").strip())
    return dict(groups)


def load_ebay_groups(path: str) -> dict[str, dict]:
    with open(path, "r", encoding="utf-8-sig") as f:
        return load_ebay_groups_from_text(f.read())


class Dolibarr:
    def __init__(self, base_url: str, api_key: str, timeout: int = 30):
        self.base = base_url.rstrip("/")
        self.s = requests.Session()
        self.s.headers["DOLAPIKEY"] = api_key
        self.s.headers["Accept"] = "application/json"
        self.timeout = timeout

    def _get(self, path: str, **params):
        r = self.s.get(f"{self.base}{path}", params=params, timeout=self.timeout)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def find_order_by_ref_client(self, ref_client: str) -> dict | None:
        """Look up by ref_client via the list endpoint, then refetch by id so
        linkedObjectsIds is populated (the list endpoint leaves it null)."""
        safe = ref_client.replace("'", "''")
        data = self._get(
            "/api/index.php/orders",
            limit=2,
            sqlfilters=f"(t.ref_client:=:'{safe}')",
        )
        if not data:
            return None
        if isinstance(data, dict) and data.get("error"):
            return None
        stub = data[0] if isinstance(data, list) else data
        if not stub:
            return None
        order_id = stub.get("id")
        if not order_id:
            return stub
        full = self._get(f"/api/index.php/orders/{order_id}")
        return full or stub

    def get_invoice(self, invoice_id: str) -> dict | None:
        return self._get(f"/api/index.php/invoices/{invoice_id}")


INVOICE_TYPE_LABELS = {
    "0": "invoice",
    "1": "replacement",
    "2": "credit_note",
    "3": "deposit",
    "4": "proforma",
    "5": "situation",
}


def reconcile(ebay_groups: dict[str, dict], dol: Dolibarr, tolerance: Decimal) -> list[dict]:
    results: list[dict] = []
    for order_num in sorted(ebay_groups):
        g = ebay_groups[order_num]
        ebay_net = g["net"]
        entry = {
            "order_number": order_num,
            "ebay_net": ebay_net,
            "ebay_rows": g["rows"],
            "ebay_types": sorted(g["types"]),
            "dolibarr_order_ref": None,
            "dolibarr_order_id": None,
            "dolibarr_net": None,
            "invoices": [],
            "status": "",
            "diff": None,
            "notes": "",
        }
        order = dol.find_order_by_ref_client(order_num)
        if not order:
            entry["status"] = "MISSING_IN_DOLIBARR"
            entry["notes"] = "No sales order with this ref_client"
            results.append(entry)
            continue
        entry["dolibarr_order_ref"] = order.get("ref")
        entry["dolibarr_order_id"] = order.get("id")

        linked = (order.get("linkedObjectsIds") or {}).get("facture") or {}
        invoice_ids = list(linked.values()) if isinstance(linked, dict) else []
        if not invoice_ids:
            entry["status"] = "NO_LINKED_INVOICES"
            entry["notes"] = f"Sales order {order.get('ref')} has no linked invoices/credit notes"
            entry["dolibarr_net"] = Decimal("0")
            entry["diff"] = ebay_net
            results.append(entry)
            continue

        dol_net = Decimal("0")
        for inv_id in invoice_ids:
            inv = dol.get_invoice(inv_id)
            if not inv:
                entry["invoices"].append({"id": inv_id, "error": "not_found"})
                continue
            t = str(inv.get("type"))
            label = INVOICE_TYPE_LABELS.get(t, f"type_{t}")
            try:
                amt = Decimal(str(inv.get("total_ht") or "0"))
            except InvalidOperation:
                amt = Decimal("0")
            if label == "credit_note" and amt > 0:
                # Dolibarr stores credit notes as positive; they reduce the order total.
                amt = -amt
            dol_net += amt
            entry["invoices"].append({
                "id": inv_id,
                "ref": inv.get("ref"),
                "type": label,
                "total_ht": amt,
            })
        entry["dolibarr_net"] = dol_net
        diff = (ebay_net - dol_net).quantize(Decimal("0.01"))
        entry["diff"] = diff
        if abs(diff) <= tolerance:
            entry["status"] = "MATCH"
        else:
            entry["status"] = "MISMATCH"
        results.append(entry)
    return results


def _fmt(v):
    if isinstance(v, Decimal):
        return f"{v:.2f}"
    return v


def print_report(results: list[dict], tolerance: Decimal) -> int:
    total = len(results)
    matches = sum(1 for r in results if r["status"] == "MATCH")
    mismatches = [r for r in results if r["status"] == "MISMATCH"]
    missing = [r for r in results if r["status"] == "MISSING_IN_DOLIBARR"]
    no_inv = [r for r in results if r["status"] == "NO_LINKED_INVOICES"]

    print(f"\n=== Reconciliation Summary ===")
    print(f"Orders compared       : {total}")
    print(f"Matches (|diff| <= {tolerance}): {matches}")
    print(f"Mismatches            : {len(mismatches)}")
    print(f"Missing in Dolibarr   : {len(missing)}")
    print(f"No linked invoices    : {len(no_inv)}")

    def _section(title: str, rows: Iterable[dict]):
        rows = list(rows)
        if not rows:
            return
        print(f"\n--- {title} ({len(rows)}) ---")
        print(f"{'Order number':<22} {'SO ref':<14} {'eBay net':>10} {'Dol net':>10} {'Diff':>10}  Invoices")
        for r in rows:
            inv_summary = ", ".join(
                f"{i.get('ref') or i.get('id')}[{i.get('type','?')}]={_fmt(i.get('total_ht'))}"
                for i in r["invoices"]
            ) or "-"
            print(
                f"{r['order_number']:<22} "
                f"{(r['dolibarr_order_ref'] or '-'): <14} "
                f"{_fmt(r['ebay_net']):>10} "
                f"{_fmt(r['dolibarr_net']) if r['dolibarr_net'] is not None else '-':>10} "
                f"{_fmt(r['diff']) if r['diff'] is not None else '-':>10}  "
                f"{inv_summary}"
            )

    _section("MISMATCH", mismatches)
    _section("MISSING IN DOLIBARR", missing)
    _section("NO LINKED INVOICES", no_inv)

    return 0 if not (mismatches or missing or no_inv) else 1


CSV_COLUMNS = [
    "status",
    "order_number",
    "ebay_net",
    "dolibarr_net",
    "diff",
    "dolibarr_order_ref",
    "dolibarr_order_id",
    "ebay_rows",
    "ebay_types",
    "invoice_count",
    "invoice_refs",
    "invoice_ids",
    "invoice_types",
    "invoice_amounts",
    "notes",
]


def _csv_row(r: dict) -> list:
    invs = r.get("invoices") or []
    return [
        r.get("status", ""),
        r.get("order_number", ""),
        _fmt(r.get("ebay_net")) if r.get("ebay_net") is not None else "",
        _fmt(r.get("dolibarr_net")) if r.get("dolibarr_net") is not None else "",
        _fmt(r.get("diff")) if r.get("diff") is not None else "",
        r.get("dolibarr_order_ref") or "",
        r.get("dolibarr_order_id") or "",
        r.get("ebay_rows", 0),
        "|".join(r.get("ebay_types") or []),
        len(invs),
        "|".join(str(i.get("ref") or "") for i in invs),
        "|".join(str(i.get("id") or "") for i in invs),
        "|".join(str(i.get("type") or "") for i in invs),
        "|".join(_fmt(i.get("total_ht")) for i in invs if i.get("total_ht") is not None),
        r.get("notes", ""),
    ]


def results_to_csv_text(results: list[dict]) -> str:
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for r in results:
        w.writerow(_csv_row(r))
    return buf.getvalue()


def write_csv_report(results: list[dict], path: str) -> None:
    """One row per eBay order. Linked invoices are flattened into '|'-joined fields."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write(results_to_csv_text(results))


def _json_default(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(f"{type(o).__name__} not serializable")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv", help="eBay payout CSV path")
    p.add_argument("--url", default=os.environ.get("DOLIBARR_URL", "https://staging.txscorp.com"))
    p.add_argument("--key", default=os.environ.get("DOLIBARR_API_KEY"))
    p.add_argument("--tolerance", type=Decimal, default=Decimal("0.01"))
    p.add_argument("--json", dest="as_json", action="store_true", help="Emit JSON instead of a text report")
    p.add_argument("--csv", dest="csv_out", help="Write a detailed CSV report to this path")
    p.add_argument("--only", choices=["mismatch", "missing", "no_invoices", "match", "all"], default="all",
                   help="Limit output to a subset")
    args = p.parse_args(argv)

    if not args.key:
        p.error("Dolibarr API key required (--key or DOLIBARR_API_KEY)")

    groups = load_ebay_groups(args.csv)
    if not groups:
        print("No eBay order rows found in CSV", file=sys.stderr)
        return 2

    dol = Dolibarr(args.url, args.key)
    results = reconcile(groups, dol, args.tolerance)

    if args.only != "all":
        wanted = {
            "mismatch": "MISMATCH",
            "missing": "MISSING_IN_DOLIBARR",
            "no_invoices": "NO_LINKED_INVOICES",
            "match": "MATCH",
        }[args.only]
        results = [r for r in results if r["status"] == wanted]

    if args.csv_out:
        write_csv_report(results, args.csv_out)
        print(f"Wrote CSV report: {args.csv_out} ({len(results)} rows)", file=sys.stderr)

    if args.as_json:
        json.dump(results, sys.stdout, default=_json_default, indent=2)
        sys.stdout.write("\n")
        return 0
    return print_report(results, args.tolerance)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
