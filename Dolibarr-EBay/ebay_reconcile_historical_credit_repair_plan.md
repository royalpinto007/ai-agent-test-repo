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

## How To Read The Examples

Each repair example uses simple numbers. The important idea is always the same:

- A credit note means eBay/customer should owe us less.
- If the full invoice was already paid before the credit was applied, the payment needs to be corrected down to the net amount.
- If the credit is larger than the invoice or no invoice can be found, the remaining value should stay as available credit instead of forcing a negative balance.

## Repair Actions

### 1. `REPAIR_SINGLE_CN_SINGLE_PAYMENT`

Staging count: `1,496` rows  
Credit amount: `$14,117.21`

Meaning:

A single module-created credit note belongs to one invoice, and that invoice has one payment. This is the simplest and most common repair.

Repair:

1. Correct the payment so it is reduced by the credit note amount.
2. Mark the credit note as available.
3. Apply the credit note to the invoice.
4. Leave the invoice paid for the correct net amount.

Example:

- Invoice `IN100`: `$1,000`
- Credit note `IC200`: `$150`
- Payment currently recorded: `$1,000`
- Correct payment should be: `$850`

After repair:

- The invoice is still paid.
- The credit note reduces the invoice by `$150`.
- The payment is corrected from `$1,000` to `$850`.
- Customer outstanding is not overstated or negative.

### 2. `REPAIR_USING_EXISTING_CN_SOURCE_INVOICE_IGNORE_ORDER_AMBIGUITY`

Staging count: `192` rows  
Credit amount: `$18,405.22`

Meaning:

The eBay order has more than one invoice, but the credit note already points to the exact invoice it was created from. We do not need to guess.

Repair:

Use the invoice already linked on the credit note, apply the credit there, and adjust that invoice payment only.

Example:

- eBay order `01-12345-67890` has two invoices: `IN100` for `$600` and `IN101` for `$400`.
- Credit note `IC200` for `$80` is already linked to `IN101`.
- Payment on `IN101` was recorded as `$400`.
- Correct payment on `IN101` should be `$320`.

After repair:

- `IC200` is applied to `IN101`.
- Payment on `IN101` is corrected from `$400` to `$320`.
- `IN100` is not touched.

### 3. `APPLY_CN_WITH_RESIDUAL_AVAILABLE_CREDIT`

Staging count: `142` rows  
Credit amount: `$17,774.20`

Meaning:

The credit note is larger than what can be applied to the invoice. We should apply what fits and keep the extra as available credit.

Repair:

1. Apply as much credit as can be applied to the source invoice.
2. Keep the remaining credit available on the customer account.
3. Do not force the invoice or customer balance below zero.

Example:

- Invoice: `$100`
- Payment recorded: `$100`
- Credit note: `$130`

After repair:

- `$100` of the credit is used against the invoice.
- `$30` remains available as customer credit.
- The invoice is not pushed to `-$30`.

### 4. `MARK_CN_AVAILABLE_STANDALONE_NO_SOURCE_INVOICE`

Staging count: `135` rows  
Credit amount: `$9,217.67`

Meaning:

The module created a credit note, but we cannot find a source invoice to apply it to. Since the credit note is ours, it should still become available credit instead of sitting unused.

Repair:

Mark the credit note as available customer credit, but do not apply it to an invoice automatically.

Example:

- Credit note `IC200`: `$75`
- No source invoice found.
- There is no safe invoice target.

After repair:

- `IC200` becomes available credit on the eBay customer account.
- Accounting can later apply, clear, or review it.
- No payment is changed automatically.

### 5. `REPAIR_GROUPED_CNS_FOR_ONE_INVOICE`

Staging count: `82` rows  
Credit amount: `$5,352.46`

Meaning:

Several module-created credit notes belong to the same invoice. They should be repaired together so the invoice/payment math stays consistent.

Repair:

Add the credit notes together, apply them all to the invoice, and correct the payment by the combined credit amount.

Example:

- Invoice `IN100`: `$1,000`
- Credit notes: `IC201 = $50`, `IC202 = $75`
- Payment currently recorded: `$1,000`
- Total credits: `$125`
- Correct payment should be `$875`.

After repair:

- Apply both credit notes to `IN100`.
- Payment is corrected from `$1,000` to `$875`.
- Invoice remains paid correctly.

### 6. `RELINK_CN_TO_ONLY_ORDER_INVOICE_THEN_REPAIR`

Staging count: `14` rows  
Credit amount: `$882.62`

Meaning:

The credit note does not directly point to an invoice, but the eBay order has exactly one invoice. Since there is only one possible target, we can use that invoice.

Repair:

1. Use the only invoice for that order as the source invoice.
2. Mark the credit note available.
3. Apply it to that invoice.
4. Adjust payment if needed.

Example:

- eBay order `01-12345-67890`
- One invoice found: `IN100`
- Credit note `IC200`: `$40`
- Payment currently recorded on `IN100`: `$500`
- Correct payment should be `$460`.

After repair:

- Treat `IN100` as the source invoice.
- Apply `IC200` to `IN100`.
- Correct the invoice payment to the net amount.

### 7. `MARK_APPLY_CN_NO_PAYMENT_REVERSAL`

Staging count: `3` rows  
Credit amount: `$771.09`

Meaning:

The credit note has a source invoice, but no payment has been recorded yet. That means there is no payment to correct.

Repair:

Mark the credit note available and apply it to the source invoice. Leave payments alone.

Example:

- Invoice `IN100`: `$500`
- Payment recorded: `$0`
- Credit note `IC200`: `$50`

After repair:

- Apply `$50` credit to invoice.
- Invoice open balance becomes `$450`.
- No payment record is changed.

### 8. `GROUPED_CN_REVIEW_PAYMENT_SHORT_OR_COMPLEX`

Staging count: `18` rows  
Credit amount: `$1,810.28`

Meaning:

There are multiple credit notes for the invoice, but the payment does not cleanly cover the full credit amount. This is still our module-created data, but it needs a rule before applying.

Repair:

Use a scripted rule or accounting decision to decide how much credit can be applied and how much should remain available.

Example:

- Invoice `IN100`: `$300`
- Credit notes total: `$400`
- Payment recorded: `$250`

Why this needs a decision:

- The credit is larger than the invoice/payment situation.
- We can apply up to the invoice amount, but there may be leftover credit.
- We need to decide whether the extra `$100` is valid available credit or whether one credit note is duplicate.

Possible after repair:

- `$300` credit is applied to close the invoice.
- `$100` stays as available credit, if accounting confirms it is valid.

### 9. `REVIEW_AMBIGUOUS_ORDER_AND_COMPLEX_PAYMENT`

Staging count: `3` rows  
Credit amount: `$103.01`

Meaning:

The eBay order has multiple invoices, and the credit/payment relationship is not clear enough from the basic invoice link.

Repair:

Use payout history or saved reconcile state to identify which invoice the credit belongs to, then repair that invoice.

Example:

- eBay order `01-12345-67890` has three invoices: `IN100`, `IN101`, `IN102`.
- Credit note `IC200`: `$35`
- Payment exists, but it is unclear which invoice should receive the credit.

Decision needed:

- If payout history shows `IC200` was created against `IN101`, apply it to `IN101`.
- If not, keep it out of automatic repair until accounting confirms the target.

### 10. `REVIEW_MISSING_SOURCE_MULTIPLE_INVOICES`

Staging count: `2` rows  
Credit amount: `$374.90`

Meaning:

The credit note has no source invoice link, and the eBay order has more than one possible invoice. We cannot safely choose one without more information.

Repair:

Use payout history, original reconcile state, or accounting review to choose the correct invoice. If no invoice can be confirmed, keep the credit available but unapplied.

Example:

- Credit note `IC200` for order `01-12345-67890`.
- Invoices found: `IN100`, `IN101`.
- No source invoice link on `IC200`.
- Credit amount: `$120`

Possible outcomes:

- Apply `$120` to `IN100` if payout history confirms it.
- Apply `$120` to `IN101` if payout history confirms it.
- Leave `$120` as available credit if no invoice target can be proven.

### 11. `NO_ACTION_ALREADY_FIXED`

Staging count: `1` row  
Credit amount: `$299.99`

Meaning:

The credit note is already available/applied in Dolibarr. It does not need repair.

Repair:

No repair should be applied.

Example:

- Credit note `IC200`: `$300`
- It already has a Dolibarr credit/discount entry.
- It is already applied to invoice `IN100`.

After review:

- Leave unchanged.
- Do not reverse payment.
- Do not apply the credit again.

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
