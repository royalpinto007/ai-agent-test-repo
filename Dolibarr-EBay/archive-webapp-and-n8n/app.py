#!/usr/bin/env python3
"""FastAPI UI in front of the n8n reconciliation webhook.

The UI uploads a CSV to /api/reconcile, which forwards it (as multipart) to
the n8n production webhook. The webhook does the Dolibarr lookups and returns
{summary, discrepancies, matches}. This shim normalises the shape for the UI.

Run:
    export N8N_WEBHOOK_URL=https://n8n.txscorp.com/webhook/ebay-reconcile
    export DOLIBARR_URL=https://staging.txscorp.com   # only for the topbar label
    uvicorn app:app --reload --port 8000
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="eBay - Dolibarr Reconciliation")


def _n8n_url() -> str:
    url = os.environ.get("N8N_WEBHOOK_URL")
    if not url:
        raise HTTPException(
            status_code=500,
            detail="N8N_WEBHOOK_URL env var is not set on the FastAPI server",
        )
    return url


def _n8n_approve_url() -> str:
    url = os.environ.get("N8N_APPROVE_WEBHOOK_URL")
    if not url:
        raise HTTPException(
            status_code=500,
            detail="N8N_APPROVE_WEBHOOK_URL env var is not set on the FastAPI server",
        )
    return url


def _n8n_pay_url() -> str:
    url = os.environ.get("N8N_PAY_WEBHOOK_URL")
    if not url:
        raise HTTPException(
            status_code=500,
            detail="N8N_PAY_WEBHOOK_URL env var is not set on the FastAPI server",
        )
    return url


def _n8n_create_invoice_url() -> str:
    url = os.environ.get("N8N_CREATE_INVOICE_WEBHOOK_URL")
    if not url:
        raise HTTPException(
            status_code=500,
            detail="N8N_CREATE_INVOICE_WEBHOOK_URL env var is not set on the FastAPI server",
        )
    return url


def _default_ebay_socid() -> str:
    return os.environ.get("DOLIBARR_DEFAULT_EBAY_SOCID", "3657")


def _to_ui_shape(r: dict) -> dict:
    """n8n emits camelCase fields; the UI expects the snake_case shape from reconcile.py."""
    return {
        "order_number":        r.get("orderNumber"),
        "ebay_net":            r.get("ebayNet"),
        "ebay_rows":           r.get("ebayRows", 0),
        "ebay_types":          r.get("ebayTypes") or [],
        "ebay_lines":          r.get("ebayLines") or [],
        "dolibarr_order_ref":  r.get("dolOrderRef"),
        "dolibarr_order_id":   r.get("dolOrderId"),
        "dolibarr_net":        r.get("dolNet"),
        "diff":                r.get("diff"),
        "status":              r.get("status"),
        "notes":               r.get("notes", ""),
        "invoices": [
            {
                "id":       i.get("id"),
                "ref":      i.get("ref"),
                "type":     i.get("type"),
                "total_ht": i.get("totalHt") if "totalHt" in i else i.get("total_ht"),
            }
            for i in (r.get("invoices") or [])
        ],
    }


def _summary_from_results(results: list[dict]) -> dict:
    """Build UI summary from normalized rows so counts and chips cannot diverge."""
    return {
        "ordersCompared": len(results),
        "matches": sum(1 for r in results if r.get("status") == "MATCH"),
        "mismatches": sum(1 for r in results if r.get("status") == "MISMATCH"),
        "missingInDolibarr": sum(1 for r in results if r.get("status") == "MISSING_IN_DOLIBARR"),
        "noLinkedInvoices": sum(1 for r in results if r.get("status") == "NO_LINKED_INVOICES"),
    }


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/info")
def api_info():
    return {
        "dolibarrUrl":    os.environ.get("DOLIBARR_URL", "https://staging.txscorp.com"),
        "n8nUrl":         os.environ.get("N8N_WEBHOOK_URL"),
        "n8nApproveUrl":  os.environ.get("N8N_APPROVE_WEBHOOK_URL"),
        "n8nPayUrl":      os.environ.get("N8N_PAY_WEBHOOK_URL"),
        "n8nCreateInvoiceUrl": os.environ.get("N8N_CREATE_INVOICE_WEBHOOK_URL"),
        "approveEnabled": bool(os.environ.get("N8N_APPROVE_WEBHOOK_URL")),
        "payEnabled":     bool(os.environ.get("N8N_PAY_WEBHOOK_URL")),
        "createInvoiceEnabled": bool(os.environ.get("N8N_CREATE_INVOICE_WEBHOOK_URL")),
        "defaultEbaySocid": _default_ebay_socid(),
    }


@app.post("/api/approve")
async def api_approve(payload: dict):
    """Forward an approval payload to the n8n approve webhook.

    Expected payload from the UI:
        { action, orderId, orderRef, orderNumber, parentInvoiceId, amount, label }
    """
    url = _n8n_approve_url()
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(url, json=payload)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach n8n approve webhook: {e}")
    if r.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"n8n approve returned HTTP {r.status_code}: {r.text[:500]}",
        )
    try:
        data = r.json()
    except ValueError:
        raise HTTPException(status_code=502, detail=f"n8n approve response was not JSON: {r.text[:300]}")
    return JSONResponse(data)


@app.post("/api/reconcile")
async def api_reconcile(file: UploadFile = File(...)):
    url = _n8n_url()
    raw = await file.read()
    import base64
    payload = {
        "filename": file.filename or "payout.csv",
        "data": base64.b64encode(raw).decode("ascii"),
    }
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            r = await client.post(url, json=payload)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach n8n: {e}")

    if r.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"n8n returned HTTP {r.status_code}: {r.text[:500]}",
        )

    try:
        data = r.json()
    except ValueError:
        raise HTTPException(status_code=502, detail=f"n8n response was not JSON: {r.text[:300]}")

    discrepancies = data.get("discrepancies") or []
    matches = data.get("matches") or []
    payout = data.get("payout")
    results = [_to_ui_shape(x) for x in matches + discrepancies]
    results.sort(key=lambda x: (x.get("status") or "", x.get("order_number") or ""))
    summary = _summary_from_results(results)
    return JSONResponse({"summary": summary, "payout": payout, "results": results})


@app.post("/api/create-invoice")
async def api_create_invoice(payload: dict):
    """Forward a create-invoice request to the n8n create-invoice webhook.

    Expected payload from the UI:
        { orderNumber, ebayNet, lines, parentSoId?, defaultSocid? }
    """
    url = _n8n_create_invoice_url()
    if not payload.get("parentSoId") and not payload.get("defaultSocid"):
        payload["defaultSocid"] = _default_ebay_socid()
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(url, json=payload)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach n8n create-invoice webhook: {e}")
    if r.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"n8n create-invoice returned HTTP {r.status_code}: {r.text[:500]}",
        )
    try:
        data = r.json()
    except ValueError:
        raise HTTPException(status_code=502, detail=f"n8n create-invoice response was not JSON: {r.text[:300]}")
    return JSONResponse(data)


@app.post("/api/pay")
async def api_pay(payload: dict):
    """Forward a pay request to the n8n pay webhook.

    Expected payload from the UI:
        { orderNumber, payoutId, payoutDateUnix, paymentTypeId?, bankAccountId?, comment? }
    """
    url = _n8n_pay_url()
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(url, json=payload)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach n8n pay webhook: {e}")
    if r.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"n8n pay returned HTTP {r.status_code}: {r.text[:500]}",
        )
    try:
        data = r.json()
    except ValueError:
        raise HTTPException(status_code=502, detail=f"n8n pay response was not JSON: {r.text[:300]}")
    return JSONResponse(data)
