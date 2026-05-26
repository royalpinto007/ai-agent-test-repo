# Test CSVs

12 hand-picked payout CSVs covering the edge cases worth exercising before
trusting the module on real data.

Each file uses the same eBay format as your real payout (preamble + header
row at line 13 + 36 data columns). Where rows are taken from real orders,
their Order numbers are real and Dolibarr will (hopefully) find SOs for
them. Where rows are synthetic, the Order numbers start with `99-FAKE-`
or `99-GHOST-` so they're easy to spot and won't collide with real eBay
data.

Regenerate any time with:

```bash
cd Dolibarr-EBay/test-csvs
python3 generate.py
```

## The suite

| File | What it tests | Expected outcome |
|------|---------------|------------------|
| `01-tiny-positive.csv` | Smallest valid payout (1 order, 1 row, +0.43) | MATCH or MISMATCH depending on whether `12-14358-49690` has a Dolibarr SO matching the amount |
| `02-tiny-negative.csv` | Smallest negative payout (1 order, 1 row, -0.33) | Tests negative-net handling and the diff display |
| `03-multi-row-order.csv` | One order with 4 CSV rows summing to zero | Confirms the **per-row breakdown** displays correctly under the eBay net cell. Also confirms zero-net handling. |
| `04-small-mixed.csv` | 5 orders, mix of positive and negative | Tests typical mixed-status reconciliation in miniature |
| `05-positive-only.csv` | 10 highest-positive-net orders | Tests several MATCH / MISMATCH rows at once; bulk Approve should work |
| `06-negative-only.csv` | All 22 negative-net orders from the original | Heaviest stress test for the credit-note creation flow |
| `07-large-amounts.csv` | 5 highest-magnitude orders ($500+) | Verifies number formatting and large-amount display |
| `08-all-synthetic.csv` | 5 fake order numbers (`99-FAKE-...`) | **All 5 should be `MISSING_IN_DOLIBARR`**. Tests the "Create invoice (no SO)" flow under your default eBay customer. Includes a zero-net row, a refund-only row, and a row with both Order + fee. |
| `09-medium-mixed.csv` | 25 real orders across the value spectrum | Realistic dress-rehearsal before the full 106 |
| `10-malformed-rows.csv` | 3 good orders + 3 deliberately-malformed rows | Tests the parser's silent-skip behaviour: rows with `--` for Order number or Net amount, and a non-numeric net, should all be ignored without an error |
| `11-empty.csv` | Header row present, no data | Tests empty-input handling — should produce "no rows" gracefully |
| `12-no-header.csv` | No eBay header at all | Should error cleanly with "Could not find header row" — tests bad-file rejection |

## Recommended testing order

For a fresh install on staging where you want to verify behaviour cleanly:

### 1. `12-no-header.csv` — bad input is rejected cleanly

Upload a CSV that doesn't even have the eBay header. The module should reject
it with a clear error message, not crash.

![Test 12 — bad header rejected](../docs/screenshots/test-12-no-header.png)

Result: red error banner *"Could not find header row in CSV. Upload an eBay
payout CSV."* — no half-rendered table, no PHP trace dump.

### 2. `11-empty.csv` — empty CSV produces an empty report

Upload a CSV with only the header row (no data). The module should treat
this as "zero orders to process", not as an error.

![Test 11 — empty CSV](../docs/screenshots/test-11-empty.png)

Result: all summary tiles read `0`, the table renders with the empty
message *"No rows match the current filter."* All buttons disabled or
absent. Nothing crashes.

### 3. `10-malformed-rows.csv` — silently skip garbage rows

Upload a CSV that has 3 real orders + 3 deliberately-malformed rows
(missing order number, missing net, non-numeric net). The parser should
silently drop the bad ones while processing the 3 good ones.

![Test 10 — first reconcile, malformed rows skipped](../docs/screenshots/test-10-malformed-a.png)

Result: summary shows 3 orders processed (not 6 — the garbage rows are
gone). The breakdown text under "eBay net" (e.g. `Other fee -0.16 · Order
+2.24`) confirms multi-row orders are grouping correctly. Notice the
payout banner: *Payout TEST-0010-MAL · May 10, 2026 · Test Bank - *0010*
— payout metadata extracted from the CSV header correctly.

Now exercise the full workflow — click **Approve** on the Mismatches, **Create invoice** on the Missing, then **Pay all**:

![Test 10 — after Approve / Create / Pay all](../docs/screenshots/test-10-malformed-b.png)

Result: row `14-14512-22342` is now MATCH (its CN sums with the existing
invoice to equal the eBay net). Other rows show their `CN <ref> CREATED`
or `INV <ref> CREATED` chips and `PAID <amount>` confirmations. The
bottom-right toast: *"Bulk pay done: 3 paid, 0 failed."*

### 4. Verify Payouts history

Sidebar → **Payouts history**. The just-settled payout should appear:

![Payouts history page](../docs/screenshots/payouts-history.png)

One row per settled payout: ID, date, method, orders count, payments
count, total paid, when, by whom. The `details ▾` link expands to show
every individual payment with clickable SO / invoice refs.

---

### Remaining tests (no screenshots yet)

4. **`01-tiny-positive.csv`** — simplest happy path. One row, one order. If anything in the rendering pipeline is broken, this surfaces it.
5. **`02-tiny-negative.csv`** — same but negative net. Tests diff sign rendering.
6. **`03-multi-row-order.csv`** — confirm the per-row breakdown shows under the eBay net cell (4 rows summing visibly).
7. **`08-all-synthetic.csv`** — 5 guaranteed-missing rows. Click **Create invoice** on one of them and confirm the new invoice appears in Dolibarr under your default eBay customer (socid 3657).
8. **`04-small-mixed.csv`** — 5 mixed-sign real orders. Test Approve on any MISMATCH, then click Pay all.
9. **`07-large-amounts.csv`** — verify $500+ amounts render correctly.
10. **`09-medium-mixed.csv`** — 25-order dress rehearsal.
11. **`06-negative-only.csv`** — heavier credit-note creation stress test.
12. **`05-positive-only.csv`** — bulk Approve happy path.

## What each file's payout metadata looks like

Each file (except `08`, `11`, `12`) has a distinct Payout ID and Payout date
so that **Payouts history** page accumulates them as separate entries when
you settle them:

| File | Payout ID | Payout date |
|------|-----------|-------------|
| `01-tiny-positive.csv` | `TEST-0001-POS` | May 01, 2026 |
| `02-tiny-negative.csv` | `TEST-0002-NEG` | May 02, 2026 |
| `03-multi-row-order.csv` | `TEST-0003-MULTI` | May 03, 2026 |
| `04-small-mixed.csv` | `TEST-0004-MIX` | May 04, 2026 |
| `05-positive-only.csv` | `TEST-0005-POS10` | May 05, 2026 |
| `06-negative-only.csv` | `TEST-0006-NEG` | May 06, 2026 |
| `07-large-amounts.csv` | `TEST-0007-BIG` | May 07, 2026 |
| `08-all-synthetic.csv` | `9000000000` | May 26, 2026 |
| `09-medium-mixed.csv` | `TEST-0009-MED` | May 09, 2026 |
| `10-malformed-rows.csv` | `TEST-0010-MAL` | May 10, 2026 |

That way you can:
- Run Pay-all on each and have them register as distinct payouts.
- Verify the payments in Dolibarr have unique `num_payment` values you can
  search by.
- Confirm the History page shows them as separate rows.

## Cleaning up your staging after testing

Test runs leave real Dolibarr records behind: any "Create invoice" you click
makes an actual Dolibarr invoice; any "Pay all" makes an actual payment.

**The safe way:** before testing, snapshot staging (db backup). After, restore.

**The lazy way:** keep all your test invoices under `socid 3657` and at
month-end have someone delete them via Dolibarr UI (Invoices list →
filter by ref_client starting `99-FAKE-` or `99-GHOST-` → Cancel + Delete).

**Don't** use these test files against production. The synthetic orders
would create real invoices for non-existent eBay sales.
