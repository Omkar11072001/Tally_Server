"""FastAPI app for creating and fetching Tally ledgers, vouchers, and stock items via XML."""

import re

import httpx
import xmltodict
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from models import CreateLedgerPayload
from purchase_models import CreatePurchasePayload
from sales_models import CreateSalesPayload
from invoice_models import CreateInvoicePayload
from xml_builder import build_ledger_xml
from purchase_xml_builder import build_purchase_xml
from sales_xml_builder import build_sales_xml
from invoice_xml_builder import build_invoice_xml
from fetch_xml_builder import (
    build_fetch_ledgers_xml,
    build_fetch_stock_items_xml,
    build_fetch_stock_summary_xml,
    build_fetch_vouchers_xml,
)
from debit_credit_api import router as debit_credit_router

app = FastAPI(
    title="Tally API",
    description="Create ledgers and vouchers in Tally via its HTTP XML interface",
    version="1.0.0",
)

TALLY_URL = "http://localhost:9000"

app.include_router(debit_credit_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/create-ledger")
async def create_ledger(payload: CreateLedgerPayload):
    xml_str = build_ledger_xml(payload)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                TALLY_URL,
                content=xml_str,
                headers={"Content-Type": "application/xml"},
            )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=502,
            detail="Cannot connect to Tally at "
            + TALLY_URL
            + ". Is Tally running with HTTP server enabled on port 9000?",
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Tally request timed out",
        )

    tally_response = response.text

    # Check for Tally error indicators in response
    is_error = (
        "LINEERROR" in tally_response
        or "ERROR" in tally_response.upper()
        and "CREATED" not in tally_response.upper()
    )

    return {
        "status": "error" if is_error else "success",
        "tally_response": tally_response,
        "xml_sent": xml_str,
    }


async def _post_to_tally(xml_str: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                TALLY_URL,
                content=xml_str,
                headers={"Content-Type": "application/xml"},
            )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=502,
            detail="Cannot connect to Tally at "
            + TALLY_URL
            + ". Is Tally running with HTTP server enabled on port 9000?",
        )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Tally request timed out")

    tally_response = response.text
    is_error = (
        "LINEERROR" in tally_response
        or "ERROR" in tally_response.upper()
        and "CREATED" not in tally_response.upper()
    )
    return {
        "status": "error" if is_error else "success",
        "tally_response": tally_response,
        "xml_sent": xml_str,
    }


@app.post("/create-purchase")
async def create_purchase(payload: CreatePurchasePayload):
    xml_str = build_purchase_xml(payload)
    return await _post_to_tally(xml_str)


@app.post("/create-sales")
async def create_sales(payload: CreateSalesPayload):
    xml_str = build_sales_xml(payload)
    return await _post_to_tally(xml_str)


@app.post("/create-invoice")
async def create_invoice(payload: CreateInvoicePayload):
    xml_str = build_invoice_xml(payload)
    return await _post_to_tally(xml_str)


async def _fetch_from_tally(xml_str: str) -> dict:
    """Send an export XML request to Tally and return the parsed response."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                TALLY_URL,
                content=xml_str,
                headers={"Content-Type": "application/xml"},
            )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=502,
            detail="Cannot connect to Tally at "
            + TALLY_URL
            + ". Is Tally running with HTTP server enabled on port 9000?",
        )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Tally request timed out")

    # Strip XML-invalid control characters and their entity references
    # that Tally sometimes includes (e.g. &#4;)
    clean_text = re.sub(r"&#\d+;", "", response.text)
    clean_text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", clean_text)

    try:
        parsed = xmltodict.parse(clean_text)
    except Exception as exc:
        return {"error": str(exc), "raw_response": clean_text[:500]}

    return parsed


def _get_tally_messages(parsed: dict) -> list[dict]:
    """Extract the TALLYMESSAGE list from a parsed Tally response."""
    msgs = (
        parsed.get("ENVELOPE", {})
        .get("BODY", {})
        .get("IMPORTDATA", {})
        .get("REQUESTDATA", {})
        .get("TALLYMESSAGE", [])
    )
    if isinstance(msgs, dict):
        msgs = [msgs]
    return msgs


def _extract_objects(parsed: dict, object_key: str) -> list[dict]:
    """Pull out only the objects matching object_key from TALLYMESSAGE list."""
    return [
        msg[object_key]
        for msg in _get_tally_messages(parsed)
        if object_key in msg
    ]


# ---- Ledger field extraction ------------------------------------------------

_LEDGER_FIELDS = [
    ("@NAME", "name"),
    ("PARENT", "group"),
    ("OPENINGBALANCE", "opening_balance"),
    ("MAILINGNAME", "mailing_name"),
    ("CURRENCYNAME", "currency"),
    ("EMAIL", "email"),
    ("LEDGERMOBILE", "mobile"),
    ("LEDGERCONTACT", "contact"),
    ("INCOMETAXNUMBER", "pan"),
    ("PARTYGSTIN", "gstin"),
    ("GSTREGISTRATIONTYPE", "gst_registration_type"),
    ("COUNTRYOFRESIDENCE", "country"),
    ("ISBILLWISEON", "bill_wise"),
    ("ISCOSTCENTRESON", "cost_centres"),
    ("DESCRIPTION", "description"),
]


def _clean_ledger(raw: dict) -> dict:
    out = {}
    for src, dst in _LEDGER_FIELDS:
        out[dst] = raw.get(src) or None
    return out


# ---- Voucher field extraction ------------------------------------------------

_VOUCHER_FIELDS = [
    ("VOUCHERNUMBER", "voucher_number"),
    ("DATE", "date"),
    ("VOUCHERTYPENAME", "voucher_type"),
    ("PARTYLEDGERNAME", "party"),
    ("NARRATION", "narration"),
    ("REFERENCE", "reference"),
    ("PARTYGSTIN", "party_gstin"),
    ("PLACEOFSUPPLY", "place_of_supply"),
    ("ISINVOICE", "is_invoice"),
    ("GUID", "guid"),
]


def _extract_ledger_entries(raw: dict) -> list[dict]:
    """Extract ledger entries from a voucher (handles both key variants)."""
    entries = []
    for key in ("ALLLEDGERENTRIES.LIST", "LEDGERENTRIES.LIST"):
        les = raw.get(key, [])
        if isinstance(les, dict):
            les = [les]
        for le in les:
            entries.append({
                "ledger": le.get("LEDGERNAME"),
                "amount": le.get("AMOUNT"),
                "is_party": le.get("ISPARTYLEDGER") == "Yes",
            })
    return entries


def _clean_voucher(raw: dict) -> dict:
    out = {}
    for src, dst in _VOUCHER_FIELDS:
        out[dst] = raw.get(src) or None

    # Calculate total amount from party ledger entry
    entries = _extract_ledger_entries(raw)
    out["amount"] = None
    for e in entries:
        if e["is_party"] and e["amount"]:
            out["amount"] = e["amount"]
            break

    out["ledger_entries"] = entries
    return out


# ---- Stock item field extraction ---------------------------------------------

_STOCK_FIELDS = [
    ("@NAME", "name"),
    ("PARENT", "group"),
    ("BASEUNITS", "unit"),
    ("OPENINGBALANCE", "opening_balance"),
    ("OPENINGVALUE", "opening_value"),
    ("OPENINGRATE", "opening_rate"),
    ("MAILINGNAME", "mailing_name"),
    ("DESCRIPTION", "description"),
    ("GSTAPPLICABLE", "gst_applicable"),
]


def _clean_stock_item(raw: dict) -> dict:
    out = {}
    for src, dst in _STOCK_FIELDS:
        out[dst] = raw.get(src) or None
    return out


def _text(val) -> str:
    """Extract text from an xmltodict value that may be a str or dict."""
    if isinstance(val, dict):
        return val.get("#text", "")
    return str(val) if val else ""


def _clean_stock_summary_item(raw: dict) -> dict:
    """Clean a STOCKITEM from the TDL Collection response."""
    return {
        "name": raw.get("@NAME", ""),
        "group": _text(raw.get("PARENT")),
        "unit": _text(raw.get("BASEUNITS")),
        "closing_balance": _text(raw.get("CLOSINGBALANCE")),
        "closing_value": _text(raw.get("CLOSINGVALUE")),
        "closing_rate": _text(raw.get("CLOSINGRATE")),
    }


# ---- GET endpoints -----------------------------------------------------------


@app.get("/ledgers")
async def get_ledgers(
    company_name: str = Query(None, description="Tally company name"),
):
    """Fetch all ledger masters from Tally."""
    if not company_name:
        raise HTTPException(status_code=400, detail="company_name is required")
    xml_str = build_fetch_ledgers_xml(company_name)
    parsed = await _fetch_from_tally(xml_str)
    if "error" in parsed:
        return parsed

    raw_ledgers = _extract_objects(parsed, "LEDGER")
    ledgers = [_clean_ledger(r) for r in raw_ledgers]
    return {"count": len(ledgers), "ledgers": ledgers}


@app.get("/api/ledger/by-gstin/{gstin}")
async def get_ledger_by_gstin(
    gstin: str,
    company_name: str = Query(None, description="Tally company name"),
    username: str | None = Query(None, description="Tally username"),
    password: str | None = Query(None, description="Tally password"),
):
    """Look up a single ledger by its GSTIN (partial or full match)."""
    if not company_name:
        raise HTTPException(status_code=400, detail="company_name is required")
    gstin_upper = gstin.strip().upper()

    xml_str = build_fetch_ledgers_xml(company_name)
    parsed = await _fetch_from_tally(xml_str)
    if "error" in parsed:
        return parsed

    raw_ledgers = _extract_objects(parsed, "LEDGER")

    for raw in raw_ledgers:
        party_gstin = (raw.get("PARTYGSTIN") or "").strip().upper()
        if gstin_upper in party_gstin:
            cleaned = _clean_ledger(raw)
            return JSONResponse(
                content={
                    "status": "success",
                    "company_name": company_name,
                    "username": username,
                    "password": password,
                    "gstin": party_gstin,
                    "ledger_name": cleaned["name"],
                    "ledger": cleaned,
                }
            )

    return JSONResponse(
        status_code=404,
        content={
            "status": "error",
            "company_name": company_name,
            "username": username,
            "password": password,
            "message": f"No ledger found for GSTIN: {gstin_upper}",
        },
    )


@app.get("/stock-items")
async def get_stock_items(
    company_name: str = Query(None, description="Tally company name"),
):
    """Fetch all stock items from Tally."""
    if not company_name:
        raise HTTPException(status_code=400, detail="company_name is required")
    xml_str = build_fetch_stock_items_xml(company_name)
    parsed = await _fetch_from_tally(xml_str)
    if "error" in parsed:
        return parsed

    raw_items = _extract_objects(parsed, "STOCKITEM")
    items = [_clean_stock_item(r) for r in raw_items]
    return {"count": len(items), "stock_items": items}


@app.get("/vouchers/purchase")
async def get_purchase_vouchers(
    company_name: str = Query(None, description="Tally company name"),
    from_date: str = Query(..., description="Start date in YYYYMMDD format"),
    to_date: str = Query(..., description="End date in YYYYMMDD format"),
):
    """Fetch purchase vouchers from Tally within a date range."""
    if not company_name:
        raise HTTPException(status_code=400, detail="company_name is required")
    xml_str = build_fetch_vouchers_xml(company_name, "Purchase", from_date, to_date)
    parsed = await _fetch_from_tally(xml_str)
    if "error" in parsed:
        return parsed

    raw_vchs = _extract_objects(parsed, "VOUCHER")
    vouchers = [_clean_voucher(r) for r in raw_vchs]
    return {"count": len(vouchers), "vouchers": vouchers}


@app.get("/vouchers/sales")
async def get_sales_vouchers(
    company_name: str = Query(None, description="Tally company name"),
    from_date: str = Query(..., description="Start date in YYYYMMDD format"),
    to_date: str = Query(..., description="End date in YYYYMMDD format"),
):
    """Fetch sales vouchers from Tally within a date range."""
    if not company_name:
        raise HTTPException(status_code=400, detail="company_name is required")
    xml_str = build_fetch_vouchers_xml(company_name, "Sales", from_date, to_date)
    parsed = await _fetch_from_tally(xml_str)
    if "error" in parsed:
        return parsed

    raw_vchs = _extract_objects(parsed, "VOUCHER")
    vouchers = [_clean_voucher(r) for r in raw_vchs]
    return {"count": len(vouchers), "vouchers": vouchers}


@app.get("/api/stock-summary")
async def get_stock_summary(
    company_name: str = Query(None, description="Tally company name"),
    username: str | None = Query(None, description="Tally username"),
    password: str | None = Query(None, description="Tally password"),
):
    """Fetch stock-in-hand (closing balance) for all stock items."""
    if not company_name:
        raise HTTPException(status_code=400, detail="company_name is required")
    xml_str = build_fetch_stock_summary_xml(company_name)
    parsed = await _fetch_from_tally(xml_str)
    if "error" in parsed:
        return parsed

    collection = (
        parsed.get("ENVELOPE", {})
        .get("BODY", {})
        .get("DATA", {})
        .get("COLLECTION", {})
    )
    raw_items = collection.get("STOCKITEM", [])
    if isinstance(raw_items, dict):
        raw_items = [raw_items]

    items = [_clean_stock_summary_item(r) for r in raw_items]
    return {
        "company_name": company_name,
        "username": username,
        "password": password,
        "count": len(items),
        "stock_items": items,
    }
