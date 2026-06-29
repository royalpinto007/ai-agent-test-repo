# eBay Reconcile Historical Credit Repair Plan

## Purpose

This document explains how to repair historical Dolibarr records created by the eBay reconciliation module when credit notes were created but not properly made available/applied before payments were recorded.

The repair scope is intentionally limited to records created by our eBay reconciliation module. We should not touch unrelated manual Dolibarr credit notes, invoices, or payments unless accounting requests separate review.

## Source Files

- Full module-only repair plan: `staging_ebay_module_only_full_repair_plan.csv`
- Module-created repairable credit rows: `staging_ebay_module_only_repairable_credit_rows.csv`
- Earlier broad candidate report: `staging_ebay_credit_repair_precise_report.csv`

## Scope Confirmed From Staging

The audit starts only from credit notes where:

```sql
note_private LIKE 'Auto-created via eBay reconciliation%'
```

That means the records are traceable to the eBay reconciliation module.

Current staging counts:

- Module-created Dolibarr documents: `2,553`
- Module-created credit notes: `2,088`
- Module-created invoices: `465`
- eBay-style payment lines: `3,644`
- Settled reconcile result rows: `3,367`

For the credit-note repair specifically:

- Module-created credit notes affected: `2,088`
- Total module-created credit note amount: `$69,108.65`
- Already fixed/applied: `1` row
- Rows with a defined automated or scripted repair path: most rows
- Rows requiring explicit manual/scripted decision rules: `23`

## Repair Action Summary

| Repair action | Rows | Credit amount |
| --- | ---: | ---: |
| `REPAIR_SINGLE_CN_SINGLE_PAYMENT` | `1,496` | `$14,117.21` |
| `REPAIR_USING_EXISTING_CN_SOURCE_INVOICE_IGNORE_ORDER_AMBIGUITY` | `192` | `$18,405.22` |
| `APPLY_CN_WITH_RESIDUAL_AVAILABLE_CREDIT` | `142` | `$17,774.20` |
| `MARK_CN_AVAILABLE_STANDALONE_NO_SOURCE_INVOICE` | `135` | `$9,217.67` |
| `REPAIR_GROUPED_CNS_FOR_ONE_INVOICE` | `82` | `$5,352.46` |
| `RELINK_CN_TO_ONLY_ORDER_INVOICE_THEN_REPAIR` | `14` | `$882.62` |
| `MARK_APPLY_CN_NO_PAYMENT_REVERSAL` | `3` | `$771.09` |
| `GROUPED_CN_REVIEW_PAYMENT_SHORT_OR_COMPLEX` | `18` | `$1,810.28` |
| `REVIEW_AMBIGUOUS_ORDER_AND_COMPLEX_PAYMENT` | `3` | `$103.01` |
| `REVIEW_MISSING_SOURCE_MULTIPLE_INVOICES` | `2` | `$374.90` |
| `NO_ACTION_ALREADY_FIXED` | `1` | `$299.99` |
| **Total** | **`2,088`** | **`$69,108.65`** |

## What Went Wrong

The intended flow should have been:

1. eBay payout shows a lower net amount than the Dolibarr invoice.
2. The module creates a credit note for the difference.
3. The credit note is marked as available in Dolibarr.
4. The credit is applied to the source invoice.
5. Only the net remaining invoice amount is paid.

Example intended flow:

- Invoice: `$1,000`
- Existing or new credit note: `$200`
- Net invoice amount after credit: `$800`
- Payment recorded: `$800`

The historical issue is that many credit notes were created and validated, but not converted/applied as Dolibarr credits before payment. In some cases, the invoice was paid as if the credit did not exist.

## Repair Actions

### 1. `REPAIR_SINGLE_CN_SINGLE_PAYMENT`

Staging count: `1,496` rows  
Credit amount: `$14,117.21`

Meaning:

A single module-created credit note is linked to one source invoice, and that invoice has one payment line. This is the cleanest case.

Repair:

1. Reduce or reverse the existing payment allocation by the credit note amount.
2. Mark the credit note as available.
3. Apply the credit note to the source invoice.
4. Recreate or adjust the payment for the net amount.

Example:

- Invoice `IN100`: `$1,000`
- Credit note `IC200`: `$150`
- Payment currently recorded: `$1,000`
- Correct payment should be: `$850`

After repair:

- Credit note `$150` is applied to invoice.
- Payment against invoice becomes `$850`.
- Invoice remains paid, but no overpayment remains.

### 2. `REPAIR_USING_EXISTING_CN_SOURCE_INVOICE_IGNORE_ORDER_AMBIGUITY`

Staging count: `192` rows  
Credit amount: `$18,405.22`

Meaning:

The eBay order has multiple invoices, but the credit note already has a direct `fk_facture_source` link to the intended source invoice.

Repair:

Use the source invoice link on the credit note instead of guessing from the order number.

Example:

- eBay order has invoices `IN100` and `IN101`.
- Credit note `IC200` is explicitly linked to `IN101`.
- Even though the order has multiple invoices, repair uses `IN101`.

After repair:

- Apply `IC200` to `IN101`.
- Adjust payment on `IN101` only.
- Leave `IN100` untouched.

### 3. `APPLY_CN_WITH_RESIDUAL_AVAILABLE_CREDIT`

Staging count: `142` rows  
Credit amount: `$17,774.20`

Meaning:

The credit note amount is larger than the amount paid or larger than the remaining invoice balance.

Repair:

1. Apply as much credit as can be applied to the source invoice.
2. Leave the remaining credit as available customer credit.
3. Do not force the invoice/customer into a negative balance.

Example:

- Invoice: `$100`
- Payment recorded: `$100`
- Credit note: `$130`

After repair:

- `$100` credit can offset the invoice.
- `$30` remains as available credit for accounting/customer review.

### 4. `MARK_CN_AVAILABLE_STANDALONE_NO_SOURCE_INVOICE`

Staging count: `135` rows  
Credit amount: `$9,217.67`

Meaning:

The module-created credit note has no usable source invoice link, and no matching invoice was found for that order.

Repair:

Mark the credit note as available customer credit, but do not apply it to an invoice automatically.

Example:

- Credit note `IC200`: `$75`
- No source invoice found.

After repair:

- `IC200` becomes available credit on the eBay customer account.
- Accounting can later apply or clear it as needed.

### 5. `REPAIR_GROUPED_CNS_FOR_ONE_INVOICE`

Staging count: `82` rows  
Credit amount: `$5,352.46`

Meaning:

There are multiple module-created credit notes for the same source invoice, but the invoice has one payment and that payment covers the total credit amount.

Repair:

Process all credit notes for that invoice together.

Example:

- Invoice `IN100`: `$1,000`
- Credit notes: `IC201 = $50`, `IC202 = $75`
- Payment currently recorded: `$1,000`
- Total credits: `$125`

After repair:

- Apply both credit notes to `IN100`.
- Correct payment becomes `$875`.

### 6. `RELINK_CN_TO_ONLY_ORDER_INVOICE_THEN_REPAIR`

Staging count: `14` rows  
Credit amount: `$882.62`

Meaning:

The credit note is missing a source invoice link, but the eBay order has exactly one invoice. That invoice can be treated as the intended source.

Repair:

1. Use the only invoice for that order as the source invoice.
2. Mark the credit note available.
3. Apply it to that invoice.
4. Adjust payment if needed.

Example:

- eBay order `01-12345-67890`
- One invoice found: `IN100`
- Credit note `IC200` has no source link.

After repair:

- Treat `IN100` as the source invoice.
- Apply `IC200` to `IN100`.

### 7. `MARK_APPLY_CN_NO_PAYMENT_REVERSAL`

Staging count: `3` rows  
Credit amount: `$771.09`

Meaning:

The credit note has a source invoice, but there is no payment line to reverse.

Repair:

Mark the credit note available and apply it to the source invoice. No payment change is needed.

Example:

- Invoice `IN100`: `$500`
- Payment recorded: `$0`
- Credit note `IC200`: `$50`

After repair:

- Apply `$50` credit to invoice.
- Invoice open balance becomes `$450`.

### 8. `GROUPED_CN_REVIEW_PAYMENT_SHORT_OR_COMPLEX`

Staging count: `18` rows  
Credit amount: `$1,810.28`

Meaning:

There are multiple credit notes for one invoice, but the payment does not cleanly cover all credit notes or payment data is not simple.

Repair:

Needs a scripted rule or accounting decision before applying.

Example:

- Invoice `IN100`: `$300`
- Credit notes total: `$400`
- Payment recorded: `$250`

Question to resolve:

Should `$300` be applied against the invoice and `$100` remain available, or is one of the credit notes duplicate/incorrect?

### 9. `REVIEW_AMBIGUOUS_ORDER_AND_COMPLEX_PAYMENT`

Staging count: `3` rows  
Credit amount: `$103.01`

Meaning:

The order has multiple invoices and the payment/source mapping is not simple enough to repair automatically.

Repair:

Needs manual or scripted mapping from payout history/state to identify the correct invoice/payment.

Example:

- eBay order has invoices `IN100`, `IN101`, `IN102`.
- Credit note exists, but source/payment relationship is unclear.

Question to resolve:

Which invoice should receive the credit?

### 10. `REVIEW_MISSING_SOURCE_MULTIPLE_INVOICES`

Staging count: `2` rows  
Credit amount: `$374.90`

Meaning:

The credit note has no source invoice link, and the order has multiple possible invoices.

Repair:

Needs manual or scripted selection of the correct invoice.

Example:

- Credit note `IC200` for order `01-12345-67890`.
- Invoices found: `IN100`, `IN101`.
- No source invoice link on `IC200`.

Question to resolve:

Should `IC200` apply to `IN100`, `IN101`, or remain standalone credit?

### 11. `NO_ACTION_ALREADY_FIXED`

Staging count: `1` row  
Credit amount: `$299.99`

Meaning:

The credit note already has a Dolibarr fixed discount/credit row.

Repair:

No repair should be applied.

Example:

- Credit note `IC200` already marked available and applied.

After review:

- Leave unchanged.

## Recommended Next Step

Start with staging only.

Suggested staging test sequence:

1. Pick 2-3 rows from `REPAIR_SINGLE_CN_SINGLE_PAYMENT`.
2. Back up the database.
3. Run repair on those rows only.
4. Confirm:
   - Credit note becomes available/applied.
   - Invoice remains paid.
   - Payment amount becomes net of credit.
   - Customer outstanding does not become negative.
5. Then test one grouped case and one residual-credit case.
6. Only after staging validation, prepare production repair scripts.

## Important Rule

Do not repair records just because they involve eBay. Repair only records traceable to the module-created credit notes unless accounting explicitly approves broader cleanup.
