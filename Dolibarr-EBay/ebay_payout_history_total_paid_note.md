# eBay Payout History: Total Paid vs Net Payout

## Example Payout

Payout ID: `7579502580`

From payout history:

| Field | Amount |
| --- | ---: |
| Debits | `$18,860.94` |
| Credits | `-$5,004.62` |
| Net payout | `$13,856.32` |
| Total paid | `$20,875.52` |

## What The Columns Mean

`Debits` is not simply the final invoice amount. It is the positive/debit side from the eBay payout file.

`Credits` is the negative/credit side from the eBay payout file, such as refunds, fees, or adjustments.

`Net payout` is the final eBay payout amount:

```text
18,860.94 - 5,004.62 = 13,856.32
```

`Total paid` is the sum of the payment item amounts saved in the payout history. This can be confusing because it is not necessarily the same as the final net payout after credits/adjustments.

## Why Total Paid Is Higher Here

For this payout, the saved reconcile summary says the actual reconciliation is clean:

| Field | Amount |
| --- | ---: |
| eBay net payout | `$13,856.32` |
| Dolibarr document net | `$13,856.32` |
| Dolibarr outstanding | `$0.00` |
| Paid all | `Yes` |

The saved report also shows:

| Field | Amount |
| --- | ---: |
| Dolibarr gross transaction/payment-like total | `$23,272.06` |
| Dolibarr adjustments/credits | `$7,019.20` |
| Net document amount | `$13,856.32` |

The visible difference is:

```text
20,875.52 - 13,856.32 = 7,019.20
```

That `$7,019.20` is the adjustment/credit amount in the saved report.

## Conclusion

The payout is reconciled correctly because:

```text
eBay net payout = Dolibarr document net
13,856.32 = 13,856.32
```

The confusing part is the `Total paid` label in payout history. It currently shows the sum of saved payment rows, while users may expect it to show the final net payout paid after credits/adjustments.

Recommended UI clarification:

- Either show `Total paid` as the final net paid/reconciled amount.
- Or rename the current column to make it clear that it is a gross/payment-row total before adjustment netting.

