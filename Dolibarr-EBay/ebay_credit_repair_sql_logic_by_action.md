# eBay Credit Repair SQL Logic By Action

This document explains what each repair action means, how the SQL fixes it, and where that logic lives in `ebay_credit_repair_apply.sql`.

Use `ebay_credit_repair_dryrun.sql` first. It has the same logic, but ends with `ROLLBACK` instead of `COMMIT`.

## Shared SQL Flow

All repair actions go through the same repair pipeline:

1. Load the repair rows into a temporary table.
   - SQL: `ebay_credit_repair_apply.sql` lines `18-30`
   - The inserted rows start at line `30` and carry `credit_id`, `credit_ref`, `source_invoice_id`, `source_invoice_ref`, `credit_amount`, `planned_apply_amount`, `payment_id`, and `repair_action`.

2. Resolve source invoice and payment.
   - SQL: lines `2127-2153`
   - If the CSV has `source_invoice_id`, the SQL uses it.
   - If the source invoice ID is missing but the action has one invoice ref, the SQL resolves that invoice by `source_invoice_ref`.
   - It also finds a single payment for that invoice when the payment ID was not already known.

3. Cap the applied credit so no invoice goes negative.
   - SQL: lines `2155-2177`
   - This is the main safety logic.
   - If an invoice has multiple credit notes, the SQL uses a running total so the combined applied amount cannot exceed the live invoice total.
   - Any extra credit remains available customer credit instead of being forced onto the invoice.

4. Build invoice-level apply totals.
   - SQL: lines `2179-2183`
   - This groups credit application by invoice/payment before updating invoice totals and payment allocations.

5. Print precheck totals.
   - SQL: lines `2185-2194`
   - These are the numbers we reviewed in dry-run, such as credit made available, credit applied to invoices, and unresolved source rows.

6. Start the real transaction.
   - SQL: line `2196`
   - In dry-run SQL, the same transaction ends with `ROLLBACK`.
   - In apply SQL, it ends with `COMMIT` at line `2310`.

7. Create available-credit rows.
   - SQL: lines `2198-2208`
   - This creates rows in `llx_societe_remise_except`.
   - This is what makes the credit note available in Dolibarr.

8. Apply credit to invoices where safe.
   - SQL: lines `2210-2237`
   - This creates negative invoice lines in `llx_facturedet`.
   - It only runs when `source_invoice_id IS NOT NULL` and `apply_amount > 0`.

9. Link the available credit row to the invoice line.
   - SQL: lines `2239-2243`
   - This connects `llx_societe_remise_except.fk_facture_line` to the credit line created in `llx_facturedet`.

10. Reduce invoice totals.
    - SQL: lines `2245-2251`
    - This lowers the invoice total by the applied credit amount.

11. Reduce payment allocation.
    - SQL: lines `2253-2257`
    - This fixes the historical overpayment by reducing `llx_paiement_facture.amount`.

12. Recalculate payment header totals.
    - SQL: lines `2259-2268`
    - This keeps shared payout payment headers balanced after the invoice-level payment line changes.

13. Mark repaired credit notes paid/closed.
    - SQL: lines `2270-2276`
    - This marks the credit note as closed because it has now been made available/applied.

14. Verify results.
    - SQL: lines `2278-2308`
    - Important checks:
      - Available-credit rows created
      - Applied invoice lines created
      - Negative invoice count
      - Negative payment line count
      - Payment header mismatch count
      - Unresolved source row count

## Action 1: `REPAIR_SINGLE_CN_SINGLE_PAYMENT`

Meaning:

One module-created credit note belongs to one invoice, and that invoice has one payment.

What SQL does:

1. The row already has a source invoice ID and payment ID in the input rows.
2. SQL keeps that source invoice and payment while building `tmp_ebay_credit_repair_raw_todo`.
3. SQL applies the full credit amount unless it would make the invoice negative.
4. SQL reduces the invoice total and payment line by the applied credit.

Where:

- Source invoice/payment resolution: lines `2133-2153`
- Apply cap: lines `2155-2177`
- Create available credit: lines `2198-2208`
- Apply invoice credit line: lines `2210-2237`
- Reduce invoice total: lines `2245-2251`
- Reduce payment allocation: lines `2253-2257`
- Recalculate payment header: lines `2259-2268`

Example:

- Invoice was paid for `$140.86`.
- Credit note is `$6.82`.
- SQL applies `$6.82`.
- Invoice/payment become `$134.04`.

## Action 2: `REPAIR_USING_EXISTING_CN_SOURCE_INVOICE_IGNORE_ORDER_AMBIGUITY`

Meaning:

The eBay order has multiple invoices, but the credit note already has a source invoice. We trust the credit note source invoice instead of guessing from the order.

What SQL does:

1. The input row carries the source invoice ID.
2. SQL uses `COALESCE(i.source_invoice_id, inv_by_ref.rowid)`, so the existing source invoice ID wins.
3. Other invoices on the same eBay order are not touched.
4. SQL applies the credit only to that source invoice, capped by the invoice total.

Where:

- Source invoice ID wins over invoice-ref lookup: lines `2138-2149`
- Scope limited to module-created credits only: lines `2145-2153`
- Apply cap: lines `2163-2166`
- Invoice/payment updates: lines `2245-2268`

Example:

- Order has invoices `IN2604-1578` and `IN2606-5520`.
- Credit note points to `IN2604-1578`.
- SQL repairs only `IN2604-1578`.
- `IN2606-5520` is not touched.

## Action 3: `APPLY_CN_WITH_RESIDUAL_AVAILABLE_CREDIT`

Meaning:

The credit note is larger than what can safely be applied to the invoice.

What SQL does:

1. SQL creates available credit for the full credit note amount.
2. SQL applies only the amount that fits on the invoice.
3. The remaining credit is left available because it is in `llx_societe_remise_except` but not fully consumed by invoice lines.

Where:

- Full credit becomes available: lines `2198-2208`
- Applied amount capped using live invoice total: lines `2163-2166`
- Running cap for multiple credit notes on one invoice: lines `2170-2175`
- Invoice line only uses `apply_amount`: lines `2223-2237`

Example:

- Invoice is `$25.68`.
- Credit note is `$27.26`.
- SQL makes `$27.26` available.
- SQL applies `$25.68`.
- Remaining `$1.58` stays available.

## Action 4: `MARK_CN_AVAILABLE_STANDALONE_NO_SOURCE_INVOICE`

Meaning:

The credit note was created by the module, but no safe invoice target exists.

What SQL does:

1. The row has no source invoice.
2. SQL sets `apply_amount = 0`.
3. SQL still creates an available-credit row.
4. SQL does not create an invoice line and does not change any payment.

Where:

- Source invoice remains null: lines `2138-2149`
- No source invoice means apply amount is zero: lines `2163-2165`
- Available credit is still created: lines `2198-2208`
- Invoice line insert requires source invoice and apply amount: line `2237`
- Payment update only happens for invoice apply totals: lines `2253-2257`

Example:

- Credit note is `$50.61`.
- No source invoice found.
- SQL makes `$50.61` available.
- No invoice/payment is changed.

## Action 5: `REPAIR_GROUPED_CNS_FOR_ONE_INVOICE`

Meaning:

Multiple module-created credit notes belong to the same invoice.

What SQL does:

1. Each credit note gets its own available-credit row.
2. SQL uses a running total per invoice so the group cannot over-apply.
3. SQL groups the final applied amount by invoice/payment.
4. The invoice and payment are reduced once by the combined applied amount.

Where:

- Running total per invoice: lines `2170-2175`
- Per-row cap after running total: lines `2163-2166`
- Group invoice/payment totals: lines `2179-2183`
- Invoice/payment updates: lines `2245-2268`

Example:

- Invoice is `$6.78`.
- Two credit notes total `$6.70`.
- SQL applies `$6.70`.
- Invoice/payment become `$0.08`.

## Action 6: `RELINK_CN_TO_ONLY_ORDER_INVOICE_THEN_REPAIR`

Meaning:

The credit note has no source invoice ID, but the order has exactly one invoice ref in the repair plan.

What SQL does:

1. The input row has `source_invoice_id = NULL` but has `source_invoice_ref`.
2. SQL resolves the invoice by `inv_by_ref.ref = i.source_invoice_ref`.
3. SQL finds the one payment line for that invoice if payment ID is missing.
4. Then it applies the same repair flow as a normal source-invoice row.

Where:

- Runtime invoice-ref lookup: line `2147`
- Resolved invoice selected by `COALESCE`: lines `2138-2143`
- Single payment lookup: lines `2127-2131`
- Payment chosen by `COALESCE(i.payment_id, pay.payment_id)`: line `2143`
- Normal apply/update flow: lines `2198-2268`

Example:

- Credit note has no source invoice ID.
- Only invoice ref is `IN2606-5556`.
- SQL resolves `IN2606-5556`, applies the credit, and adjusts that invoice/payment.

## Action 7: `MARK_APPLY_CN_NO_PAYMENT_REVERSAL`

Meaning:

The credit note has a source invoice, but there is no payment line to reduce.

What SQL does:

1. SQL creates available credit.
2. SQL applies the credit to the invoice.
3. SQL reduces the invoice total.
4. Payment update is skipped because there is no payment ID.

Where:

- Source invoice resolution: lines `2138-2149`
- Available credit creation: lines `2198-2208`
- Invoice credit line creation: lines `2210-2237`
- Invoice total update: lines `2245-2251`
- Payment update requires payment match and therefore does nothing when payment is null: lines `2253-2257`

Example:

- Invoice is `$267.89`.
- Credit note is `$261.53`.
- No payment exists.
- SQL applies credit and leaves invoice balance at `$6.36`.
- No payment row is changed.

## Action 8: `GROUPED_CN_REVIEW_PAYMENT_SHORT_OR_COMPLEX`

Meaning:

Multiple credit notes belong to one invoice, but the payment/credit situation is not clean enough to assume full application without a cap.

What SQL does:

1. SQL still repairs it because the data is module-created and source invoice can be identified.
2. SQL does not blindly apply all credits.
3. SQL caps the group by the live invoice total.
4. Any excess remains available credit.

Where:

- Module-only safety filter: lines `2150-2153`
- Group running total/cap: lines `2170-2175`
- Apply amount cap: lines `2163-2166`
- Full available credit creation: lines `2198-2208`
- Invoice/payment reduction only by capped amount: lines `2245-2268`

Example:

- Invoice/payment is `$63.32`.
- Combined credit notes are `$67.36`.
- SQL applies `$63.32`.
- Extra `$4.04` stays available.

## Action 9: `REVIEW_AMBIGUOUS_ORDER_AND_COMPLEX_PAYMENT`

Meaning:

The repair report labelled this as review, but the credit note has a source invoice in the repair file. Since the source invoice is present and the credit is module-created, SQL can repair it safely using that source invoice.

What SQL does:

1. SQL uses the source invoice ID from the row.
2. SQL does not pick another invoice from the order.
3. If no payment ID exists, only invoice credit application happens.
4. If payment ID exists, payment allocation is reduced too.

Where:

- Uses source invoice ID directly: lines `2138-2149`
- Module-created credit filter: lines `2150-2153`
- Apply cap: lines `2163-2166`
- Invoice apply: lines `2210-2251`
- Payment update, if payment exists: lines `2253-2268`

Example:

- Order has multiple invoices.
- Credit row says source invoice is `IN2604-0516`.
- SQL repairs `IN2604-0516` only.
- If there is no payment line, no payment change is made.

## Action 10: `REVIEW_MISSING_SOURCE_MULTIPLE_INVOICES`

Meaning:

The credit note has no source invoice and multiple possible invoice targets. SQL must not guess.

What SQL does:

1. The row has no source invoice ID and no single source invoice ref.
2. SQL sets `apply_amount = 0`.
3. SQL creates available credit only.
4. No invoice or payment is changed.

Where:

- No invoice gets resolved: lines `2138-2149`
- Null source invoice means zero apply amount: lines `2163-2165`
- Available credit is still created: lines `2198-2208`
- Invoice line insert is blocked by `source_invoice_id IS NOT NULL AND apply_amount > 0`: line `2237`
- Verification allows this action to remain source-null: lines `2299-2301`

Example:

- Credit note is `$74.95`.
- Possible invoices are `IN2606-5451`, `IN2606-5855`, `IN2606-5903`, `IN2606-5912`.
- SQL does not choose between them.
- Credit becomes available for accounting to apply later.

## Not Touched: `NO_ACTION_ALREADY_FIXED`

Meaning:

This one credit note was already fixed before the repair script.

What SQL does:

The row is not inserted into the repair SQL input at all. That is why the SQL total is `$68,808.66` while the full report total is `$69,108.65`.

Where:

- The apply SQL says it generated `2087` rows, excluding already-fixed rows: line `4`
- The safety filter also skips any credit note that already has a `llx_societe_remise_except` row: lines `2150-2153`

Example:

- Full report total: `$69,108.65`
- Already fixed: `$299.99`
- SQL repair total: `$68,808.66`

## Dry Run vs Apply

Dry run:

- Runs the same logic.
- Prints the same checks.
- Ends with `ROLLBACK`, so all temporary changes are discarded.

Apply:

- Runs the same logic.
- Prints the same checks.
- Ends with `COMMIT` at line `2310`, so changes are saved.

