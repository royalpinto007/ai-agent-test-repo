# eBay Reconciliation — Dolibarr module

Reconciles eBay payouts against Dolibarr invoices natively, inside Dolibarr.

A user uploads the eBay payout CSV from **Bank/Cash → eBay payouts → Reconcile
a payout**. The module matches each eBay order to a Dolibarr Sales Order by
`ref_client`, lets the user fix mismatches with one click (creates credit
notes, missing invoices), and records payments using the payout's own ID and
date. A **Payouts history** page lists every settled run.

No external services — no FastAPI, no n8n, no Python. Just PHP + Dolibarr's
own classes.

## Install

### Option A — through Dolibarr's Module Installer (zip upload)

1. **Home → Setup → Modules/Applications → Deploy/install external module from file**.
2. Upload `ebayreconcile-1.0.6.zip`.
3. Activate **eBay Reconciliation** in the modules list (the green toggle).
4. **Home → Setup → Modules/Applications → eBay Reconciliation → Setup** to
   review the defaults (default eBay customer socid, bank account id, payment
   type id, match tolerance).
5. Grant permissions to users:
   - `Use eBay reconciliation` — for anyone who uploads CSVs.
   - `Approve adjustments / create invoices / record payments` — for finance.
   - `Configure eBay reconciliation defaults` — for admins.

### Option B — manual copy

1. Extract the zip into `htdocs/custom/` so the path becomes
   `htdocs/custom/ebayreconcile/`.
2. Activate the module via **Home → Setup → Modules/Applications**.
3. Same setup + permissions steps as above.

## Use it

Once enabled, a new entry appears in the left menu under **Bank/Cash → eBay
payouts** with two sub-pages: **Reconcile a payout** and **Payouts history**.

For day-to-day use, see [docs/USER_GUIDE.md](../docs/USER_GUIDE.md) in the
repo (same user guide that documented the old web-app version — it still
applies, just open the page from Dolibarr's menu instead of a separate URL).

## What the module does in Dolibarr

| User action | What gets created or changed in Dolibarr |
|-------------|------------------------------------------|
| Upload CSV → click Reconcile | Nothing — read-only comparison |
| Click **Approve** on a Mismatch row | New credit note (draft → validated), then converted to a customer discount balance, then applied to the source invoice. The source invoice's `remaintopay` drops by the credit. |
| Click **Create invoice** on a Missing row | New invoice (draft → validated) under the configured default eBay customer (socid 3657 by default). One line per eBay CSV row. |
| Click **Create invoice** on a No-invoices row | Same, but linked to the existing Sales Order via `origin_type=commande`. |
| Click **Pay all** | A `Paiement` record per unpaid invoice for every row, using the payout's own ID as `num_payment` and the payout's date. Payments are linked to the configured bank account. Invoices flip to `paye=1`. |

## Configuration (admin)

**Setup → Modules → eBay Reconciliation → Setup** lets the admin set:

| Setting | Default | What it controls |
|---------|---------|-----------------|
| Default eBay customer (socid) | `3657` | Customer that "Missing in Dolibarr" invoices are created under |
| Bank account | `1` | Which bank account payments are credited to |
| Payment type | `2` (VIR) | Payment method recorded on each payment |
| Match tolerance | `0.01` | Absolute diff below this is MATCH |

Stored as Dolibarr constants (`EBAYRECONCILE_DEFAULT_SOCID`, etc.), so they're
per-database and survive module disable/enable.

## Permissions

| Permission | Default | Who needs it |
|------------|---------|--------------|
| `ebayreconcile.use` | enabled | Anyone allowed to upload payouts and view reports |
| `ebayreconcile.write` | disabled | Anyone allowed to write to Dolibarr (Approve, Create invoice, Pay) |
| `ebayreconcile.admin` | disabled | Anyone allowed to change defaults |

`write` is intentionally disabled by default — only grant to finance / accounting users.

## Files

```
ebayreconcile/
├── core/modules/modEbayReconcile.class.php   # module descriptor
├── class/EbayReconciler.class.php            # main reconciliation logic
├── lib/ebayreconcile.lib.php                 # shared helpers
├── admin/setup.php                           # admin config page
├── reconcile.php                             # main user page (upload + table)
├── action.php                                # AJAX endpoint: approve / create_invoice / pay / save_payout
├── history.php                               # Payouts history page
├── css/ebayreconcile.css                     # styles
├── js/ebayreconcile.js                       # frontend (filters, sorts, AJAX)
├── langs/en_US/ebayreconcile.lang            # translations
├── sql/llx_ebayreconcile_payout.sql          # history table DDL
└── sql/llx_ebayreconcile_payout.key.sql      # indexes
```

## Dolibarr classes used

The module uses Dolibarr's own PHP classes directly — no REST API roundtrips:

| Class | Used for |
|-------|---------|
| `Facture` | Read invoices/CNs, create + validate new ones |
| `Commande` | Read sales orders (when linking new invoices to them) |
| `DiscountAbsolute` | Convert validated CN into a customer balance and apply it |
| `Paiement` | Record payments + link to bank line |

This means every action runs as the logged-in Dolibarr user, respects entity
isolation, and produces the same audit-log entries you'd get if a human did it
through the Dolibarr UI.

## Compatibility

- Dolibarr **18+** (uses standard module conventions and modern Facture / Paiement APIs).
- PHP **7.4+**.
- Requires the **Bank/Cash** module enabled (for the menu placement + `Paiement::addPaymentToBank()`).

## Known quirks

- The CSV is parsed in PHP using a small RFC-4180-ish parser. It handles
  quoted fields with embedded commas. It does **not** handle escaped
  quotes-inside-quotes (which the eBay payout CSV doesn't use).
- The last reconcile result is stashed in `$_SESSION` so action.php can read
  per-order context (eBay lines) without re-uploading. If your PHP session
  has a low size limit, very large payouts (> ~10,000 orders) may need a
  bumped `session.gc_*` / size config. Typical payouts are 50–500 orders.
- Payment deletion isn't exposed by `Paiement` in some Dolibarr versions —
  if you need to undo a Pay all, do it from the Dolibarr UI (open the
  invoice → click the trash icon next to the payment).
