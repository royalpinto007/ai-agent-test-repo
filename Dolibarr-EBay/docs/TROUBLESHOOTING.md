# Troubleshooting

Common problems and what to do about them. The most useful diagnostic in
Dolibarr is the server-side **dolibarr.log** (path configured in
`Home → Setup → Other setup → Log path`) — every failed action writes
the exception there with a stack trace.

If your problem isn't here, browser DevTools → Network tab is the next stop.
Find the failing `action.php` call and look at its response body — PHP
exceptions come back as text we can pinpoint.

---

## "Filename does not match the expected name syntax"

**Where you see it:** Uploading the zip via "Deploy/install external module from file".

**Why:** Dolibarr enforces the pattern `<modulename>-<version>.zip`. A bare
`ebayreconcile.zip` is rejected.

**Fix:** Use the file named `ebayreconcile-1.0.6.zip` from this repo. Don't
rename it.

---

## "Module deployed" but it doesn't appear in the modules list

**Why:** Probably extracted to the wrong path, or Dolibarr's cache is stale.

**Fix:**
- On the server, verify the folder is at `htdocs/custom/ebayreconcile/`
  (not `htdocs/custom/dolibarr-module-ebayreconcile/`).
- Clear Dolibarr's cache: **Home → Admin tools → Purge cache**.
- Reload the Modules page.

---

## Module won't enable

**Where you see it:** Red error banner after toggling the module on.

**Common causes & fixes:**

### "Table 'llx_ebayreconcile_payout' already exists"

A previous install left the table behind. Either:
- Drop it manually if you're sure you don't need the history:
  ```sql
  DROP TABLE llx_ebayreconcile_payout;
  ```
- Or just ignore the warning — the table already exists, the module will use
  it. Try enabling again; the second attempt usually succeeds.

### "Class 'DolibarrModules' not found"

You uploaded into the wrong folder. The module must be under `htdocs/custom/`
**not** `htdocs/modules/`. Check the directory layout.

### Permission denied writing to `htdocs/custom/`

Your install has restricted file perms. Either fix the perms or use the
manual-copy install path (see [SETUP.md](SETUP.md#install-manual-copy--if-zip-upload-is-blocked)).

---

## Menu entry doesn't appear under Bank/Cash

**Why:** The `fk_menu` key for the Bank/Cash top menu varies between
Dolibarr installs — sometimes `bank`, sometimes `accountancy`.

**Fix:**

1. Confirm the module is enabled.
2. Confirm your user has `ebayreconcile.use` permission.
3. **Home → Admin tools → Purge cache** then log out and back in.

If still missing:

4. Edit `dolibarr-module-ebayreconcile/core/modules/modEbayReconcile.class.php`.
   Find the three `$this->menu` entries and change `'fk_menu' => 'fk_mainmenu=bank'`
   to whatever your install uses. Common alternatives: `accountancy`,
   `bills`, `agenda`.
5. Re-zip, re-upload, re-enable.

---

## Upload page loads but reconciliation errors out

**Where you see it:** Red error banner above the upload form after submitting.

### "Could not find header row in CSV"

The uploaded file isn't an eBay payout CSV (wrong file type, wrong export
template, or the header line uses a different label).

**Fix:** Export the payout from eBay Seller Hub → Payments → click into the
payout → **Download report**. Default settings should include the
"Transaction creation date" column the module expects.

### "CSV missing required columns"

The CSV is from an older eBay export format or a heavily customised template.

**Fix:** Re-export with default eBay columns. We require: `Transaction
creation date`, `Type`, `Order number`, `Net amount`, `Payout date`,
`Payout ID`, `Payout method`.

### PHP error (white page or trace dump)

Open browser DevTools → Network tab → click the failed `reconcile.php`
request → response. The full PHP error + stack trace will be there. Paste it
and we'll patch.

---

## "Approve fails"

**Where you see it:** Click Approve, modal Confirm, then a red error message
instead of the green chip.

### "Call to undefined method Facture::markAsCreditAvailable"

Older Dolibarr versions used a different method name (`setCreditNoteValid`).

**Fix:** Edit `dolibarr-module-ebayreconcile/action.php`, find the
`markAsCreditAvailable` call near line 90, and try the alternative method
name for your version.

### "Apply discount failed: link_to_invoice"

Method name on `DiscountAbsolute` evolved between versions
(`link_to_invoice` / `useDiscount` / `applyDiscount`).

**Fix:** Edit `action.php`, find `$discount->link_to_invoice(0, $parentInvoiceId)`,
swap to the variant your version uses. Quickest way: open
`htdocs/core/class/discount.class.php` on the server, grep for `public function`
to see what's available.

### "Create failed" (during the initial CN insert)

Could be:
- Customer (socid) doesn't exist or is set to status=closed → check Customers list.
- Required field your Dolibarr instance has marked mandatory but our payload
  doesn't set → add it to `makeLine()` in `action.php`.

---

## "Create invoice fails" for Missing / No-invoices rows

Same Facture-class issues as Approve above (the create-invoice flow is the
same `Facture` class).

Additional case:

### "No customer (socid) available for this order"

For a "Missing in Dolibarr" row, the module uses the configured default
socid. If that constant isn't set or points at a non-existent customer:

**Fix:** **Setup → Modules → eBay Reconciliation → Setup** → set
**Default eBay customer (socid)** to a real customer id.

---

## "Pay all" is greyed out — "resolve N first"

**What it means:** You still have N rows that aren't reconciled — either
Mismatches you haven't approved, or Missing / No-invoices rows you haven't
clicked Create invoice on.

**Fix:** Filter to those statuses (click the chip), work through them, then
the Pay button lights up.

---

## "Pay all" runs but some rows fail

**Look at the toast:** "Bulk pay done: X paid, Y failed". The detail per
failure is in `dolibarr.log` on the server.

### "addPaymentToBank failed"

Bank account ID is wrong — the configured account doesn't exist or your
user doesn't have permissions on it.

**Fix:** **Setup → Modules → eBay Reconciliation → Setup** → set the right
Bank account id. (Find it under Bank → Accounts → click → URL `id=N`.)

### Invoice already paid

If you click Pay all twice on the same row, the second time you'll see "0
paid, 1 nothing to pay" — the module skips already-paid invoices. That's
correct behaviour, not an error.

### Zero-amount invoice (eBay net = 0)

If a payout includes an order whose net sums to exactly zero (e.g. a refund
that perfectly cancels a sale), the "Create invoice" step makes an invoice
totalling 0. There's no balance to settle, so Pay all reports it as
"nothing to pay" — also correct behaviour. The Action column shows a
*"no balance"* chip rather than a *"paid"* one.

Before v1.0.4, this was misleadingly reported as "1 failed" in the bulk
toast. Upgrade if you're seeing that on zero-amount orders.

---

## "Payouts history" page is empty after a successful Pay all

**Why:** The save-to-history step is a separate AJAX call. If it failed
silently, the payments were created but the history row wasn't.

**Fix:**
- Check `dolibarr.log` for any `INSERT INTO llx_ebayreconcile_payout` error.
- Most likely: the table doesn't exist (module enable didn't run the SQL).
  Disable and re-enable the module to force schema creation.

Note: the payments themselves are still in Dolibarr (search
`llx_paiement.num_paiement` for the payout ID), they just don't appear in
this module's history page.

---

## Undoing a test action

### Undo a draft credit note or invoice

If you tested an Approve / Create invoice and want to remove the result
before going further:

- Open the document in Dolibarr UI (use the green chip's "view" link in the
  module's table).
- If status = Draft (0): click the trash icon — deletes cleanly.
- If status = Validated (1): you need to first **Cancel** (sets status=2),
  then **Delete**.

### Undo a payment

- Open the parent invoice.
- "Payments" section → trash icon next to the payment. Dolibarr will
  un-mark the invoice as paid and remove the bank-line.

---

## Where to dig deeper

| What | Where |
|------|-------|
| Last PHP error from the module | Server `dolibarr.log` (path in Setup → Other setup → Log path) |
| What the action call returned | Browser DevTools → Network → click the failed `action.php` request → Response tab |
| What the SQL was | If `dolibarr.log` is enabled with debug level, queries appear there. Also: enable Dolibarr's debug bar (Setup → Display → Show technical info) |
| Which menu key your install uses | View page source on any logged-in Dolibarr page; menu items have `data-mainmenu="..."` attributes |
| Whether a Dolibarr class method exists | On the server: `grep "public function methodname" htdocs/core/class/*.class.php htdocs/compta/**/*.class.php` |
