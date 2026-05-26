# User Guide

Plain-English walkthrough of every screen, every status, and every button.

If anything is unclear, jump to [Troubleshooting](TROUBLESHOOTING.md).

---

## What this tool does

You sell on eBay. eBay pays you in batches called **payouts**, and gives you a CSV
listing every order that was part of each payout.

Your accounting lives in **Dolibarr** — every sale should have a Sales Order
(SO) and an Invoice, and once a customer pays, the invoice gets marked paid.

This tool **compares one eBay payout against Dolibarr** and helps you close the
loop:

1. Match every eBay order to its Dolibarr Sales Order and invoices.
2. Show you what doesn't line up.
3. Let you fix it with one click per row (create credit notes, create missing
   invoices, etc.).
4. Once everything matches, mark all the invoices paid in one click.
5. Keep a history of payouts you've settled.

---

## The big picture in 4 steps

```
   1. Upload          2. Review         3. Fix              4. Pay
   ───────────       ──────────         ─────────           ─────────
   eBay payout CSV → Reconciliation  → Resolve any        → Pay all matches
                     table             mismatches /
                                       missing rows
```

You'll typically do this once per eBay payout (i.e., every few days).

---

## How to open the tool

In Dolibarr's top menu, click **Bank/Cash**. In the left sidebar that appears,
look for the **eBay payouts** group. Click **Reconcile a payout**.

(If you don't see it, you don't have permission yet — ask an admin to tick
"Use eBay reconciliation" on your user account.)

---

## Step 1 — Upload your eBay payout file

The page opens with an upload panel at the top. Drag your eBay payout CSV in
(or click to browse), then hit **Reconcile**.

It takes about 10–30 seconds for a typical payout (~100 orders) because
the tool queries Dolibarr's database directly to look up every order.

**Where do you get the CSV?** From eBay Seller Hub → Payments → click into a
payout → **Download report**. The file looks like
`eBay Payout_7461554484_TXS - 4-21-26 (1).csv`.

---

## Step 2 — Read the results

When reconciliation finishes, you see two things:

### A. Summary tiles at the top

```
Orders     Matches      Mismatches      Missing       No invoices
  106         40             52             11             3
```

- **Orders**: how many unique eBay orders were in your payout.
- **Matches**: orders where eBay says the same total as Dolibarr — these are
  already perfect, nothing to do but mark them paid.
- **Mismatches**: orders where eBay and Dolibarr disagree on the amount. You'll
  need to approve an adjustment.
- **Missing**: eBay orders that have **no Sales Order at all** in Dolibarr. You
  need to create an invoice for them.
- **No invoices**: orders where a Sales Order exists in Dolibarr but **no
  invoice yet**. You need to create one.

> Numbers should always add up: `Matches + Mismatches + Missing + No invoices = Orders`.

### B. The orders table

One row per eBay order, with these columns:

| Column | What it means |
|--------|---------------|
| **Status** | A colored badge: Match (green), Mismatch (red), Missing (orange), No invoices (purple). |
| **Order number** | The eBay order number (e.g. `09-14518-31202`). |
| **eBay net** | What eBay paid you for this order. If the order had multiple eBay rows (a sale plus a refund, for example), they're listed underneath in small text. |
| **Dolibarr net** | What Dolibarr currently shows as billed for this order. |
| **Diff** | eBay minus Dolibarr. Green = positive (eBay paid more than billed). Red = negative (eBay paid less than billed). Zero = match. |
| **SO ref** | The Sales Order in Dolibarr — clickable, opens the SO directly in Dolibarr. |
| **Invoices / credit notes** | List of every invoice and credit note linked to this order in Dolibarr — also clickable. |
| **Notes** | Free-text note explaining edge cases ("No SO with this ref_client", etc.). |
| **Action** | What you can do for this row — see [Step 3](#step-3--fix-what-doesnt-match). |

### Filters and search

Above the table:

- **Status chips** (All, Match, Mismatch, Missing, No invoices) — click one to
  show only those rows. Counts on each chip update in real time.
- **Search box** — type any order number, SO ref, or invoice ref to filter the
  list.
- Click any column header to **sort**.

---

## Step 3 — Fix what doesn't match

This is the main workflow. Each non-MATCH row tells you what action to take.

### MATCH — nothing to do

eBay and Dolibarr agree on the amount. Skip these. They'll be handled by **Pay
all** at the end.

### MISMATCH — Approve to create a credit note (or adjustment invoice)

eBay's number differs from Dolibarr's. The most common cause: eBay deducted
fees or applied a refund that Dolibarr doesn't know about.

**Click the "Approve" button on the row.** A modal pops up showing:

- The exact difference (e.g. `-2.00`).
- What we're about to create (a **credit note** if Dolibarr is overcharging,
  an **additional invoice** if Dolibarr is undercharging).
- Which invoice it will link to.

Click **Confirm**. In about 3 seconds, the tool does 4 things in Dolibarr:

1. Creates the credit note (or invoice) — initially as a draft.
2. Validates it — it gets a real reference number like `IC2605-0521`.
3. Marks the credit note as an available customer balance (only for credit notes).
4. Applies it against the original invoice. The invoice's "remain to pay" drops
   by exactly the difference.

The row turns light green, shows a **`✓ CN IC2605-0521 applied`** chip, and now
mathematically matches eBay's number.

**Approve all mismatches at once:** there's a blue **`✓✓ Approve all
mismatches`** button at the top of the table. Click it, confirm in the
preview modal, and the tool processes every Mismatch row in parallel (3 at a
time). You'll see a progress bar and final summary.

### MISSING — Create invoice (no SO existed)

There's no record in Dolibarr at all for this eBay order. eBay says you sold
something to a buyer; Dolibarr doesn't know.

**Click the "Create invoice" button.** A modal shows:

- Which customer it'll go under (a generic "eBay Sales" customer — `socid 3657`).
- The eBay net total.
- The exact line items that will appear on the invoice — one per CSV row.
  E.g. for an order with a refund + fee + shipping label charge, you'll see 3
  lines.

Click **Confirm**. The tool creates the invoice in Dolibarr and validates it.

The row turns light green, shows a **`✓ INV IN2605-2848`** chip.

> Note: there's no Sales Order created — just the invoice. If your accounting
> process requires an SO too, ask your admin to extend the workflow.

### NO_LINKED_INVOICES — Create invoice (SO exists, no invoice yet)

Dolibarr has a Sales Order but never had an invoice raised against it.

**Click the "Create invoice" button.** Same modal as above, except now it
shows the linked SO ref (e.g. `SO2604-0930`) instead of the default customer —
the new invoice will be properly linked to that SO.

Click **Confirm**. Same outcome — invoice created, validated, row turns green.

---

## Step 4 — Mark everything paid

Once every row is either originally Match or has been adjusted via Approve /
Create invoice, the green **`💳 Pay all (N)`** button at the top of the table
lights up. The count `(N)` is how many invoices still need a payment
recorded.

> If the button is greyed out with text "Pay all (resolve X first)", it means
> there are still X rows you haven't dealt with. Filter to those statuses and
> finish them, then come back.

Click **Pay all**. The tool:

1. For each row, asks Dolibarr which invoices are still unpaid for that order.
2. Creates a payment in Dolibarr for each one using **the payout's own
   metadata from your CSV**:
   - **Payout ID** as the payment reference (`7461554484`).
   - **Payout date** as the payment date (`Apr 21, 2026`).
   - **Payment method** as "Credit Transfer" against your CityNational bank
     account.
3. Marks each invoice as paid (`paye = 1`).
4. Skips any row where the invoice is somehow negative (the customer is owed
   money, no payment to record there).

You'll see a progress bar. At the end, a green toast shows the total and a
**View history** link.

---

## Payouts history page

Bank/Cash → **eBay payouts → Payouts history** in the left menu.

You'll see every payout you've settled, newest first:

- **Payout ID**, date, payment method.
- Number of orders and payments.
- Total amount paid.
- When you settled it and which user did it.
- A **`details ▾`** link — click to expand a sub-table showing every individual
  payment in that payout (with clickable SO and invoice refs).

This history is stored in Dolibarr's database (table
`llx_ebayreconcile_payout`), not your browser — so it persists across
machines and users. Anyone with the "Use eBay reconciliation" permission
can see it.

---

## Quick cheat sheet

| You see... | You do... | Result in Dolibarr |
|------------|-----------|--------------------|
| **Match** badge | Nothing for now, Pay all will handle it | (no change yet) |
| **Mismatch** badge | Click **Approve** → Confirm | New credit note created, validated, applied to source invoice |
| **Missing** badge | Click **Create invoice** → Confirm | New invoice under "eBay Sales" customer |
| **No invoices** badge | Click **Create invoice** → Confirm | New invoice linked to the existing Sales Order |
| All rows green / chipped | Click **Pay all** | Every unpaid invoice gets a payment record using the payout's own ID and date |
| Want to review past runs | Side menu → **Payouts history** | Browse all settled payouts |

---

## Downloads

At the top of the table:

- **CSV** — downloads a flat CSV report of every order with its status, eBay
  net, Dolibarr net, diff, SO ref, invoice list, and notes. Open in Excel /
  Google Sheets.
- **JSON** — same data, JSON format, for if you want to feed it into another
  system.

Both are generated in your browser from the current table — no extra server
round-trip.

---

## Why some things look the way they do

**An order is grouped from multiple eBay rows.** The same order can have a
"sale" row, a "refund" row, a "fee" row, etc. — the tool sums them and shows
the total in the eBay net column, with the individual rows in smaller text
below so you can see exactly what made up that total.

**The credit note made the invoice go negative.** When eBay refunds the
customer more than the original sale (rare, but happens), applying the credit
makes the invoice's remaining balance go below zero. That's correct — your
customer is now owed that money. The Pay button will skip those rows because
there's nothing to pay; it's a customer credit balance for next time.

**A row shows green chip but still says "Mismatch" badge.** That's because
the status badge reflects what the reconcile found, before you fixed it. After
you click Approve, the row gets a **`applied`** chip but the original status
badge stays — so you remember what state it was in originally. The math is
fixed; the badge is historical.

---

## What this tool will NOT do

- Mass-create Sales Orders for missing orders. We only create invoices for
  those. If your process needs an SO too, talk to your admin.
- Touch Dolibarr's customer (third party) records — no new customers are
  created. Missing orders all go under your one configured "eBay Sales"
  customer.
- Modify the original Sales Order's totals. SOs are historical records of the
  agreement; adjustments live on the invoice and credit note side.
- Undo a payment. Once you've clicked Pay all, you'd have to cancel
  payments manually in Dolibarr's UI.
