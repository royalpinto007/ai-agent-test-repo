# Setup Guide

How to install and configure the eBay Reconciliation module in Dolibarr.
Aimed at the person standing up the system, not the day-to-day user.

For day-to-day use, see the [User Guide](USER_GUIDE.md).

---

## What you need

| Piece | Why |
|-------|-----|
| **Dolibarr 18+** (we target 22.x) | Where everything lives. The module runs inside Dolibarr; nothing external. |
| **Admin user** | To install + enable the module and set permissions. |
| **Bank/Cash module enabled** | The menu lands under Bank/Cash, and payment-recording uses bank accounts. |
| **One Dolibarr customer set up as your "eBay sales" customer** | Records for "Missing in Dolibarr" rows get created under this customer. In our staging that's socid 3657 ("eBay Fixed Price US (JKComputers) seller"). |

That's the entire dependency list. No Python, no n8n, no separate server.

---

## Install (zip upload)

**1.** Log into Dolibarr as an admin user.

**2.** **Home → Setup → Modules/Applications**.

**3.** Find **"Deploy/install external module from file"** (button or tab near the top of the modules list).

**4.** Upload **[`ebayreconcile-1.0.5.zip`](../ebayreconcile-1.0.5.zip)** from this repo.

> Filename matters. Dolibarr requires `<modulename>-<version>.zip`. Don't rename it.

You should see a green "Module deployed" confirmation. Dolibarr extracted it into `htdocs/custom/ebayreconcile/`.

**5.** In the modules list, search for `eBay`. Toggle **"eBay Reconciliation"** on (red → green).

If the toggle errors, see [Troubleshooting → "Module won't enable"](TROUBLESHOOTING.md#module-wont-enable).

---

## Install (manual copy — if zip upload is blocked)

If `htdocs/custom/` isn't writable by the web server (some hardened installs):

```bash
# On the Dolibarr server (or via SCP):
cd /path/to/htdocs/custom
unzip /path/to/ebayreconcile-1.0.5.zip
chown -R www-data:www-data ebayreconcile        # adjust user/group to your setup
chmod -R u+rwX,g+rX,o+rX ebayreconcile
```

Then enable from the Modules list as in step 5 above.

---

## Configure defaults

**Home → Setup → Modules/Applications → eBay Reconciliation → Setup** (gear icon on the module row).

| Setting | Default | What it controls |
|---------|---------|-----------------|
| **Default eBay customer (socid)** | `3657` | The customer used when a "Missing" row needs an invoice but there's no SO to derive it from. |
| **Bank account** | `1` | Which Dolibarr bank account the recorded payments are credited to. |
| **Payment type** | `2` (VIR / Credit Transfer) | The payment method recorded on each payment. |
| **Match tolerance** | `0.01` | Absolute difference below this is treated as MATCH. |

**How to find your real IDs:**

- **socid:** Customers → click your eBay customer → URL shows `?socid=N` or `?id=N`.
- **Bank account ID:** Bank → Accounts → click your account → URL shows `?id=N`.
- **Payment type ID:** Setup → Dictionaries → Payment types → look up VIR's id (commonly `2`).

Save. These get stored as Dolibarr constants (`EBAYRECONCILE_DEFAULT_SOCID`, etc.) and persist across module disable/enable.

---

## Set up permissions

The module ships three permission flags. Only `use` is on by default; the others are off so finance work is gated.

**Home → Setup → Users & groups → [user] → Permissions** (or set them on a Group).

| Permission | Default | Give it to... |
|------------|---------|--------------|
| `ebayreconcile.use` | ✅ enabled | Anyone allowed to upload payouts and view reports |
| `ebayreconcile.write` | ❌ disabled | Finance/accounting users — controls Approve, Create invoice, Pay buttons |
| `ebayreconcile.admin` | ❌ disabled | Admins who can change the defaults above |

Without `write`, the UI loads in read-only mode (no buttons in the Action column). That's the right setting for view-only roles.

---

## Verify it works

After install + enable + permissions:

**1.** Top menu → **Bank/Cash** (Banks).

**2.** Left sidebar should show:
```
eBay payouts
├─ Reconcile a payout
└─ Payouts history
```

**3.** Click **Reconcile a payout** → you should see the upload form.

**4.** Upload [`eBay Payout_7461554484_TXS - 4-21-26 (1).csv`](../eBay%20Payout_7461554484_TXS%20-%204-21-26%20(1).csv) (or any payout CSV).

**5.** Wait ~10–30 seconds (PHP queries Dolibarr's tables directly — no API hops). You should see the summary tiles and the orders table.

**6.** Pick one Mismatch row → click **Approve** → preview modal → Confirm. The row should turn green with a `CN <ref>` chip, and the corresponding credit note should exist in Dolibarr (Bills → Credit notes).

If step 6 errors, see [Troubleshooting → "Approve fails"](TROUBLESHOOTING.md#approve-fails).

---

## Architecture summary

```
   Your browser
        │
        │  HTTPS to Dolibarr
        ▼
   Dolibarr (this module)
        │
        │  PHP class calls (Facture, Commande, Paiement, DiscountAbsolute)
        ▼
   Dolibarr's own database (MySQL/MariaDB)
```

No external services. Every action runs as the logged-in Dolibarr user and produces the same audit-log entries you'd get if a human did the same operations through the Dolibarr UI.

---

## Rotating credentials

There are no module-level credentials to rotate. Authentication is just the
Dolibarr user's normal login session. Rotate user passwords through
Dolibarr's standard user management as usual.

---

## Upgrading the module

When a new version ships:

1. Download the new `ebayreconcile-X.Y.Z.zip`.
2. Same upload path: **Setup → Modules/Applications → Deploy/install external module from file**.
3. Dolibarr will detect the existing install and overwrite it. Module settings (defaults, history table data) are preserved.
4. Toggle the module off and back on if any new DB columns were added (Dolibarr re-runs the SQL migrations on enable).

---

## Uninstalling

**Home → Setup → Modules/Applications → eBay Reconciliation** → toggle off.

This disables the module but **keeps the database table** (`llx_ebayreconcile_payout`) and its history rows. If you want a full purge:

```sql
DROP TABLE llx_ebayreconcile_payout;
DELETE FROM llx_const WHERE name LIKE 'EBAYRECONCILE_%';
```

Then delete the `htdocs/custom/ebayreconcile/` folder from disk.

---

## What was the old setup?

If you've worked with this tool before, you may remember the FastAPI + n8n
version. That has been replaced. The old code is preserved in
`Dolibarr-EBay/archive-webapp-and-n8n/` for reference but is no longer the
deployment path. The module supersedes it completely:

| What | Old (web-app) | New (module) |
|------|---------------|--------------|
| Where it runs | Separate Python server + n8n | Inside Dolibarr |
| Env vars | 4 webhook URLs + key | None |
| Setup time | ~30 min (n8n imports + creds + uvicorn) | ~3 min (upload zip, enable, set permissions) |
| Network hops per action | 3 | 0 |
| Audit trail | n8n executions only | Native Dolibarr audit log |
