"""Debit Note and Credit Note voucher endpoints for Tally integration."""

import re

import httpx
import xmltodict
from fastapi import APIRouter, HTTPException, Query

from debit_credit_models import CreateCreditNotePayload, CreateDebitNotePayload
from debit_credit_xml_builder import build_credit_note_xml, build_debit_note_xml

router = APIRouter()

TALLY_URL = "http://localhost:9000"


# ---- helpers (same pattern as app.py) ----------------------------------------

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


async def _fetch_from_tally(xml_str: str) -> dict:
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

    clean_text = re.sub(r"&#\d+;", "", response.text)
    clean_text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", clean_text)

    try:
        parsed = xmltodict.parse(clean_text)
    except Exception as exc:
        return {"error": str(exc), "raw_response": clean_text[:500]}

    return parsed


def _get_tally_messages(parsed: dict) -> list[dict]:
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
    return [
        msg[object_key]
        for msg in _get_tally_messages(parsed)
        if object_key in msg
    ]


def _extract_ledger_entries(raw: dict) -> list[dict]:
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


def _clean_voucher(raw: dict) -> dict:
    out = {}
    for src, dst in _VOUCHER_FIELDS:
        out[dst] = raw.get(src) or None

    entries = _extract_ledger_entries(raw)
    out["amount"] = None
    for e in entries:
        if e["is_party"] and e["amount"]:
            out["amount"] = e["amount"]
            break

    out["ledger_entries"] = entries
    return out


# ---- Create endpoints --------------------------------------------------------


@router.post("/create-debit-note")
async def create_debit_note(payload: CreateDebitNotePayload):
    """Create one or more Debit Note vouchers in Tally."""
    xml_str = build_debit_note_xml(payload)
    return await _post_to_tally(xml_str)


@router.post("/create-credit-note")
async def create_credit_note(payload: CreateCreditNotePayload):
    """Create one or more Credit Note vouchers in Tally."""
    xml_str = build_credit_note_xml(payload)
    return await _post_to_tally(xml_str)


# ---- Fetch endpoints ---------------------------------------------------------

def _build_fetch_vouchers_xml(
    company_name: str,
    voucher_type: str,
    from_date: str,
    to_date: str,
) -> str:
    """Build XML to fetch vouchers of a given type within a date range."""
    import xml.etree.ElementTree as ET

    envelope = ET.Element("ENVELOPE")
    header = ET.SubElement(envelope, "HEADER")
    req = ET.SubElement(header, "TALLYREQUEST")
    req.text = "Export Data"

    body = ET.SubElement(envelope, "BODY")
    export_data = ET.SubElement(body, "EXPORTDATA")
    request_desc = ET.SubElement(export_data, "REQUESTDESC")
    rn = ET.SubElement(request_desc, "REPORTNAME")
    rn.text = "Voucher Register"

    sv = ET.SubElement(request_desc, "STATICVARIABLES")
    fmt = ET.SubElement(sv, "SVEXPORTFORMAT")
    fmt.text = "$$SysName:XML"
    company = ET.SubElement(sv, "SVCURRENTCOMPANY")
    company.text = company_name
    vt = ET.SubElement(sv, "VOUCHERTYPENAME")
    vt.text = voucher_type
    fd = ET.SubElement(sv, "SVFROMDATE")
    fd.text = from_date
    td = ET.SubElement(sv, "SVTODATE")
    td.text = to_date

    ET.indent(envelope, space="  ")
    return ET.tostring(envelope, encoding="unicode", xml_declaration=False)


@router.get("/vouchers/debit-notes")
async def get_debit_note_vouchers(
    company_name: str = Query(None, description="Tally company name"),
    from_date: str = Query(..., description="Start date in YYYYMMDD format"),
    to_date: str = Query(..., description="End date in YYYYMMDD format"),
):
    """Fetch Debit Note vouchers from Tally within a date range."""
    if not company_name:
        raise HTTPException(status_code=400, detail="company_name is required")
    xml_str = _build_fetch_vouchers_xml(company_name, "Debit Note", from_date, to_date)
    parsed = await _fetch_from_tally(xml_str)
    if "error" in parsed:
        return parsed

    raw_vchs = _extract_objects(parsed, "VOUCHER")
    vouchers = [_clean_voucher(r) for r in raw_vchs]
    return {"count": len(vouchers), "vouchers": vouchers}


@router.get("/vouchers/credit-notes")
async def get_credit_note_vouchers(
    company_name: str = Query(None, description="Tally company name"),
    from_date: str = Query(..., description="Start date in YYYYMMDD format"),
    to_date: str = Query(..., description="End date in YYYYMMDD format"),
):
    """Fetch Credit Note vouchers from Tally within a date range."""
    if not company_name:
        raise HTTPException(status_code=400, detail="company_name is required")
    xml_str = _build_fetch_vouchers_xml(company_name, "Credit Note", from_date, to_date)
    parsed = await _fetch_from_tally(xml_str)
    if "error" in parsed:
        return parsed

    raw_vchs = _extract_objects(parsed, "VOUCHER")
    vouchers = [_clean_voucher(r) for r in raw_vchs]
    return {"count": len(vouchers), "vouchers": vouchers}
