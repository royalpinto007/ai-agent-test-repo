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

Real staging example:

- eBay order: `01-14548-61803`
- Invoice: `IN2604-1161`
- Credit note: `IC2606-0735`
- Payment: `PAY2604-0115`
- Payout: `7462176191`
- Invoice/payment currently recorded: `$140.86`
- Module-created credit note amount: `$6.82`
- Correct net payment should be: `$134.04`

After repair:

- The invoice is still paid.
- The credit note reduces the invoice by `$6.82`.
- The payment is corrected from `$140.86` to `$134.04`.
- Customer outstanding is not overstated or negative.

### 2. `REPAIR_USING_EXISTING_CN_SOURCE_INVOICE_IGNORE_ORDER_AMBIGUITY`

Staging count: `192` rows  
Credit amount: `$18,405.22`

Meaning:

The eBay order has more than one invoice, but the credit note already points to the exact invoice it was created from. We do not need to guess.

Repair:

Use the invoice already linked on the credit note, apply the credit there, and adjust that invoice payment only.

Real staging example:

- eBay order: `02-14575-10487`
- Possible invoices on the order: `IN2604-1578`, `IN2606-5520`
- Credit note: `IC2606-0751`
- Credit note amount: `$32.75`
- Source invoice already stored on the credit note: `IN2604-1578`
- Payment: `PAY2604-0131`
- Payout: `7462176191`
- Invoice/payment currently recorded on `IN2604-1578`: `$31.08`

After repair:

- `IC2606-0751` is applied to `IN2604-1578` because the credit note already points there.
- `IN2606-5520` is not touched.
- Since the credit is `$1.67` higher than the invoice/payment, the extra value should remain available credit instead of forcing a negative invoice balance.

### 3. `APPLY_CN_WITH_RESIDUAL_AVAILABLE_CREDIT`

Staging count: `142` rows  
Credit amount: `$17,774.20`

Meaning:

The credit note is larger than what can be applied to the invoice. We should apply what fits and keep the extra as available credit.

Repair:

1. Apply as much credit as can be applied to the source invoice.
2. Keep the remaining credit available on the customer account.
3. Do not force the invoice or customer balance below zero.

Real staging example:

- eBay order: `04-14600-08898`
- Invoice: `IN2605-1899`
- Credit note: `IC2606-0957`
- Payment: `PAY2605-0379`
- Payout: `7487039580`
- Invoice/payment currently recorded: `$25.68`
- Credit note amount: `$27.26`

After repair:

- `$25.68` of the credit is used against `IN2605-1899`.
- `$1.58` remains available as customer credit.
- The invoice is not pushed to `-$1.58`.

### 4. `MARK_CN_AVAILABLE_STANDALONE_NO_SOURCE_INVOICE`

Staging count: `135` rows  
Credit amount: `$9,217.67`

Meaning:

The module created a credit note, but we cannot find a source invoice to apply it to. Since the credit note is ours, it should still become available credit instead of sitting unused.

Repair:

Mark the credit note as available customer credit, but do not apply it to an invoice automatically.

Real staging example:

- eBay order: `02-14459-65870`
- Credit note: `IC2606-0913`
- Credit note amount: `$50.61`
- Source invoice found: none
- Payment to adjust: none safely identified

After repair:

- `IC2606-0913` becomes available credit on the eBay customer account.
- Accounting can later apply, clear, or review it.
- No payment is changed automatically.

### 5. `REPAIR_GROUPED_CNS_FOR_ONE_INVOICE`

Staging count: `82` rows  
Credit amount: `$5,352.46`

Meaning:

Several module-created credit notes belong to the same invoice. They should be repaired together so the invoice/payment math stays consistent.

Repair:

Add the credit notes together, apply them all to the invoice, and correct the payment by the combined credit amount.

Real staging example:

- eBay order: `03-14545-96631`
- Invoice: `IN2604-1181`
- Credit notes: `IC2606-0752` and `IC2606-1774`
- Payment: `PAY2604-0132`
- Payout: `7462176191`
- Invoice/payment currently recorded: `$6.78`
- Combined credit note amount: `$6.70`
- Correct net payment should be: `$0.08`

After repair:

- Apply both credit notes to `IN2604-1181`.
- Payment is corrected from `$6.78` to `$0.08`.
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

Real staging example:

- eBay order: `10-14561-27101`
- Credit note: `IC2606-0945`
- Credit note amount: `$4.88`
- Source invoice on the credit note: missing
- Only invoice found for the order: `IN2606-5556`

After repair:

- Treat `IN2606-5556` as the source invoice because it is the only invoice for that order.
- Apply `IC2606-0945` to `IN2606-5556`.
- If that invoice has an over-recorded payment, correct the payment to the net amount.

### 7. `MARK_APPLY_CN_NO_PAYMENT_REVERSAL`

Staging count: `3` rows  
Credit amount: `$771.09`

Meaning:

The credit note has a source invoice, but no payment has been recorded yet. That means there is no payment to correct.

Repair:

Mark the credit note available and apply it to the source invoice. Leave payments alone.

Real staging example:

- eBay order: `05-14496-55088`
- Invoice: `IN2604-0640`
- Credit note: `IC2606-1370`
- Invoice amount: `$267.89`
- Credit note amount: `$261.53`
- Payment recorded: none

After repair:

- Apply `$261.53` credit to `IN2604-0640`.
- Invoice open balance becomes `$6.36`.
- No payment record is changed.

### 8. `GROUPED_CN_REVIEW_PAYMENT_SHORT_OR_COMPLEX`

Staging count: `18` rows  
Credit amount: `$1,810.28`

Meaning:

There are multiple credit notes for the invoice, but the payment does not cleanly cover the full credit amount. This is still our module-created data, but it needs a rule before applying.

Repair:

Use a scripted rule or accounting decision to decide how much credit can be applied and how much should remain available.

Real staging example:

- eBay order: `01-14560-63539`
- Invoice: `IN2604-1360`
- Credit notes: `IC2606-0738` and `IC2606-1593`
- Payment: `PAY2604-0118`
- Payout: `7462176191`
- Invoice/payment currently recorded: `$63.32`
- Combined credit note amount: `$67.36`

Why this needs a decision:

- The combined credit is `$4.04` higher than the payment/invoice amount in this group.
- We can apply up to the invoice amount, but there may be leftover credit.
- We need to decide whether the extra `$4.04` is valid available credit or whether one credit note is duplicate.

Possible after repair:

- `$63.32` credit is applied to close the invoice.
- `$4.04` stays as available credit, if accounting confirms it is valid.

### 9. `REVIEW_AMBIGUOUS_ORDER_AND_COMPLEX_PAYMENT`

Staging count: `3` rows  
Credit amount: `$103.01`

Meaning:

The eBay order has multiple invoices, and the credit/payment relationship is not clear enough from the basic invoice link.

Repair:

Use payout history or saved reconcile state to identify which invoice the credit belongs to, then repair that invoice.

Real staging example:

- eBay order: `21-14465-88754`
- Possible invoices on the order: `IN2604-0516`, `IN2605-2676`
- Credit notes in the group: `IC2606-1160` for `$20.75`, `IC2606-1694` for `$33.54`
- Combined credit note amount: `$54.29`
- Source invoice shown in the report: `IN2604-0516`
- Invoice amount: `$784.55`
- Simple payment line in the report: none

Decision needed:

- Confirm from payout history or saved reconcile state whether these credits belong to `IN2604-0516`.
- If confirmed, repair `IN2604-0516`.
- If not confirmed, keep it out of automatic repair until accounting confirms the target.

### 10. `REVIEW_MISSING_SOURCE_MULTIPLE_INVOICES`

Staging count: `2` rows  
Credit amount: `$374.90`

Meaning:

The credit note has no source invoice link, and the eBay order has more than one possible invoice. We cannot safely choose one without more information.

Repair:

Use payout history, original reconcile state, or accounting review to choose the correct invoice. If no invoice can be confirmed, keep the credit available but unapplied.

Real staging example:

- eBay order: `(no order #)`
- Credit note: `IC2606-0992`
- Credit note amount: `$74.95`
- Possible invoices found: `IN2606-5451`, `IN2606-5855`, `IN2606-5903`, `IN2606-5912`
- No source invoice link on `IC2606-0992`.
- No single invoice target can be proven from the credit note itself.

Possible outcomes:

- Apply `$74.95` to the correct invoice if payout history confirms it.
- Leave `$74.95` as available credit if no invoice target can be proven.

### 11. `NO_ACTION_ALREADY_FIXED`

Staging count: `1` row  
Credit amount: `$299.99`

Meaning:

The credit note is already available/applied in Dolibarr. It does not need repair.

Repair:

No repair should be applied.

Real staging example:

- eBay order: `09-14819-22344`
- Invoice: `IN2606-6201`
- Credit note: `IC2606-2838`
- Payment: `PAY2606-3157`
- Payout: `STAGE-1021-SINGLE-09-14819-22344`
- Payment amount: `$1,000.00`
- Credit note amount: `$299.99`
- The credit note already has the Dolibarr fixed discount/credit row.

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
