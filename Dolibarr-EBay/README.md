# Dolibarr ↔ eBay Reconciliation

A native **Dolibarr module** that reconciles eBay payouts against Dolibarr
invoices, lets you fix any mismatches with one click, and records payments —
all inside Dolibarr, no external services.

```
   1. Upload          2. Review         3. Fix              4. Pay
   ───────────       ──────────         ─────────           ─────────
   eBay payout CSV → Reconciliation  → Resolve any        → Pay all matches
                     table             mismatches /
                                       missing rows
```

## Install

The module is packaged as **[`ebayreconcile-1.0.7.zip`](ebayreconcile-1.0.7.zip)** —
upload it through Dolibarr's "Deploy/install external module from file"
admin page. See [the module README](dolibarr-module-ebayreconcile/README.md)
for the full install / setup / permissions guide.

Once installed, find it in the left menu under **Bank/Cash → eBay payouts**.

## Documentation

| Doc | For whom |
|-----|----------|
| [Setup Guide](docs/SETUP.md) | Install + configure the module: zip upload, defaults, permissions |
| [User Guide](docs/USER_GUIDE.md) | Day-to-day: every screen, every status, every button — in plain English |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | Common error messages and fixes |
| [Module README](dolibarr-module-ebayreconcile/README.md) | Inside the module folder — Dolibarr classes used, file layout, version-compatibility notes |

## What's in this folder

| Path | What it is |
|------|------------|
| **`dolibarr-module-ebayreconcile/`** | The module source — copy into `htdocs/custom/ebayreconcile/` if you prefer manual install |
| **`ebayreconcile-1.0.7.zip`** | Packaged module for upload via Dolibarr's module installer |
| `docs/` | The user guide + troubleshooting docs |
| `eBay Payout_7461554484_TXS - 4-21-26 (1).csv` | Sample CSV for testing |
| `archive-webapp-and-n8n/` | Previous standalone Python/FastAPI + n8n implementation — kept for historical reference, no longer the recommended deployment |

## Why a module instead of an external app

The previous version was a Python FastAPI web app that called n8n webhooks
that called the Dolibarr REST API. That worked but had four moving parts:
Python, n8n, FastAPI, and the Dolibarr API. Every action was three
network hops.

This version is **pure PHP inside Dolibarr**. It uses Dolibarr's own classes
(`Facture`, `Commande`, `Paiement`, `DiscountAbsolute`) directly — no
network calls, no shared credentials, no separate hosting. Actions run as
the logged-in Dolibarr user, respect entity isolation, and produce the
same audit-log entries you'd get if a human did it through Dolibarr's UI.

| | Web-app version (archived) | Module (this version) |
|---|---|---|
| Where it runs | Separate server (Python + uvicorn) | Inside Dolibarr |
| Auth | n8n holds the API key | Uses the logged-in user's permissions |
| Deps | Python 3.12, FastAPI, ngrok, n8n, 4 workflows | Dolibarr 18+ |
| Setup | env vars + 4 n8n workflow imports + credential wiring | Upload one zip, enable, done |
| Network hops per action | 3 (browser → FastAPI → n8n → Dolibarr) | 0 |
| Audit trail | None (n8n's webhook history only) | Native Dolibarr audit log |
